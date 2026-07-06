#!/usr/bin/env python3
"""
MoatDaily - Mechanical Pre-Filter + optional Gemini vision/copy-accuracy check

The mechanical pass only checks what code CAN reliably check: resolution,
corruption, copy length/presence/hashtags, the disclaimer, no stray em dashes,
and a structural safety net (no detected face bleeding into the reserved text
panel). It does NOT judge whether the photo is relevant or whether the caption
invented facts - those are subjective/semantic and require an actual look.

When `review.gemini_api_key` is set in settings.yaml, this script also calls
Gemini (vision + text) to judge exactly that, and fills ai_verdict/ai_notes
automatically. With no key configured, ai_verdict/ai_notes stay null and it's
the `review-post` skill's job (a human/vision-capable agent) to fill them, or
publish falls back to mechanical_status alone.

Usage: python scripts/review_post.py
"""

import json
import os
from datetime import datetime
from pathlib import Path

import yaml
from PIL import Image

EXPECTED_SIZE = (1080, 1350)  # both static and carousel are 4:5

GEMINI_TIMEOUT_MS = 120_000  # per-request HTTP timeout, so a network stall degrades to "unavailable"
                             # instead of hanging indefinitely (observed directly: no timeout hung
                             # 6+ minutes). 120s, not 30-60s: an image+JSON-schema call was observed
                             # genuinely succeeding at ~99s under slow-but-working API latency - it
                             # wasn't stuck, just slow, so the bound needs headroom above that.

GEMINI_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "FAIL"]},
        "notes": {"type": "string"},
    },
    "required": ["verdict", "notes"],
}

# Mirrors skills/review-post/SKILL.md's Step 2 checklist verbatim, plus a new
# copy-accuracy item no mechanical check can catch. Keep the two in sync.
GEMINI_PROMPT_TEMPLATE = """You are reviewing an Instagram post for a news account before it publishes. Judge the attached rendered image against this checklist and respond with strict JSON only.

Checklist:
- Relevance: is the photo genuinely about THIS story - the right person, company, place, or event? Not a generic stand-in.
- Composition: is the subject fully visible and well-placed within the photo zone (top ~62% of the frame)? Not awkwardly cropped or cut off mid-face.
- No foreign watermark/logo: does the hero photo carry another outlet's logo, masthead, or watermark anywhere in the frame? Hard FAIL if so, regardless of how the image was sourced.
- Copy accuracy: does the headline/subline/caption below invent any fact, number, date, quote, or name that is NOT present in the source text below? Hard FAIL if so.

Post headline: {headline}
Post subline: {subline}
Post caption: {caption}

Source title: {source_title}
Source description: {source_description}
Source text: {source_text}

Respond with JSON: {{"verdict": "PASS" or "FAIL", "notes": "one sentence explaining why"}}"""


def run_gemini_check(brief, image_path, settings):
    """Automated stand-in for review-post skill Step 2 (vision + copy-accuracy).

    Returns (verdict, notes) - verdict is "PASS"/"FAIL", or None if unavailable
    (no api key, SDK missing, or every model in the chain failed). None means
    "skip", never "FAIL" - so a Gemini outage degrades to today's mechanical-only
    behavior instead of blocking every post.
    """
    review_cfg = (settings or {}).get("review", {}) or {}
    api_key = (review_cfg.get("gemini_api_key") or "").strip()
    if not api_key or not image_path or not Path(image_path).exists():
        return None, None

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None, None

    models = [review_cfg.get("gemini_model") or "gemini-3.5-flash"]
    models += list(review_cfg.get("gemini_fallback_models") or [])

    copy = brief.get("copy", {})
    prompt = GEMINI_PROMPT_TEMPLATE.format(
        headline=copy.get("headline", {}).get("text", ""),
        subline=copy.get("subline", {}).get("text", ""),
        caption=copy.get("caption", {}).get("text", ""),
        source_title=brief.get("source_title", ""),
        source_description=brief.get("source_description", ""),
        source_text=brief.get("source_text", ""),
    )

    try:
        # Explicit timeout: a hung network call here (observed directly - an SDK
        # call with no timeout blocked for 6+ minutes on a transient network blip)
        # would otherwise stall review_post.py and, since publish_instagram.py
        # also calls this function, the publish stage too.
        client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS))
        uploaded = client.files.upload(file=str(image_path))
    except Exception as e:
        print(f"[WARN] Gemini file upload failed: {e}")
        return None, None

    for model in models:
        try:
            interaction = client.interactions.create(
                model=model,
                input=[
                    {"type": "text", "text": prompt},
                    {"type": "image", "uri": uploaded.uri, "mime_type": uploaded.mime_type},
                ],
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": GEMINI_JSON_SCHEMA,
                },
            )
            result = json.loads(interaction.output_text)
            verdict = result.get("verdict")
            if verdict in ("PASS", "FAIL"):
                return verdict, result.get("notes")
        except Exception as e:
            print(f"[WARN] Gemini check failed on {model}: {e}")
            continue

    return None, None


def load_config():
    root = Path(__file__).parent.parent
    with open(root / "config" / "settings.yaml") as f:
        settings = yaml.safe_load(f)
    with open(root / "config" / "brand.yaml") as f:
        brand = yaml.safe_load(f)
    return settings, brand, root


def check_image_quality(image_path):
    """Mechanical checks on the rendered image file itself."""
    issues = []
    try:
        img = Image.open(image_path)
        width, height = img.size

        if (width, height) != EXPECTED_SIZE:
            issues.append(f"Size {width}x{height} != expected {EXPECTED_SIZE[0]}x{EXPECTED_SIZE[1]} (4:5)")

        file_size = os.path.getsize(image_path)
        if file_size < 50_000:  # Less than 50KB is suspicious
            issues.append(f"File size too small: {file_size/1024:.1f}KB (possible blank/corrupt image)")

        pixels = list(img.getdata())
        sample = pixels[::max(1, len(pixels)//100)]  # Sample ~100 pixels
        unique_colors = len(set(sample))
        if unique_colors < 5:
            issues.append(f"Image appears blank/uniform ({unique_colors} unique colors in sample)")

        if img.mode not in ("RGB", "RGBA"):
            issues.append(f"Unexpected color mode: {img.mode}")

    except Exception as e:
        issues.append(f"Cannot open image: {e}")

    return issues


def check_face_in_panel(image_path, photo_zone_ratio):
    """
    Structural safety net: the reserved-panel layout should make it impossible
    for a subject to end up under the headline, but this catches it if a cutout
    (or a future template change) ever regresses that guarantee.
    """
    try:
        import cv2
        import assets as assets_mod  # reuse the bundled-cascade path resolution

        img = Image.open(image_path).convert("RGB")
        width, height = img.size
        panel_top = int(height * photo_zone_ratio)

        import numpy as np
        cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
        face_cascade = cv2.CascadeClassifier(assets_mod._haarcascade_path())
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

        for (x, y, w, h) in faces:
            face_bottom = y + h
            if face_bottom > panel_top + h * 0.3:  # more than a sliver dips into the panel
                return ["A detected face overlaps the text panel - subject may be hidden under the headline"]
    except Exception:
        pass  # best-effort safety net, never blocks the pipeline on its own failure
    return []


def check_copy_quality(brief):
    """Check copy/caption presence, length, hashtags, and the no-em-dash rule."""
    issues = []
    copy = brief.get("copy", {})
    is_carousel = brief.get("post_type", "static") == "carousel"

    headline = copy.get("headline", {}).get("text", "")
    subline = copy.get("subline", {}).get("text", "")

    if is_carousel:
        slides = copy.get("carousel_slides", {}).get("slides", [])
        if not slides:
            issues.append("Missing carousel_slides.slides")
        elif any(not s.get("text") for s in slides):
            issues.append("A carousel slide is missing text")
    else:
        if not headline:
            issues.append("Missing headline text")
        elif len(headline.split()) > 15:
            issues.append(f"Headline too long: {len(headline.split())} words (max 12)")

        if not subline:
            issues.append("Missing subline text")

    caption = copy.get("caption", {}).get("text", "")
    if not caption:
        issues.append("Missing caption text")
    elif len(caption) > 2200:
        issues.append(f"Caption too long: {len(caption)} chars (max 2200)")
    elif len(caption) < 100:
        issues.append(f"Caption too short: {len(caption)} chars (needs substance)")

    if caption and "#" not in caption:
        issues.append("No hashtags in caption")

    if caption and "editorial" not in caption.lower() and "educational" not in caption.lower():
        issues.append("Missing image credit/disclaimer in caption")

    fields_to_check = [("headline", headline), ("subline", subline), ("caption", caption)]
    if is_carousel:
        for i, slide in enumerate(copy.get("carousel_slides", {}).get("slides", [])):
            fields_to_check.append((f"slide {i + 1}", slide.get("text", "")))

    for field_name, text in fields_to_check:
        if "—" in text or "–" in text:
            issues.append(f"Em dash found in {field_name} - use a hyphen instead")

    return issues


def check_brand_compliance(brief):
    """The renderer needs at least one hint to find a relevant photo."""
    issues = []
    assets_spec = brief.get("assets", {})
    has_sourcing_hint = bool(
        assets_spec.get("image_url")
        or assets_spec.get("primary_query")
        or assets_spec.get("entities")
    )
    if not has_sourcing_hint and brief.get("post_type", "static") != "carousel":
        issues.append("No image sourcing hint defined (assets.image_url/primary_query/entities) - image may be generic/irrelevant")
    return issues


def check_has_real_image(render):
    """A falsy image_source means resolve_hero_image found nothing usable and
    the renderer fell back to the brand gradient - not a real photo. Carousels
    carry a list (one source per slide); every slide needs a real image."""
    if not render:
        return ["No render record found"]
    source = render.get("image_source")
    ok = all(source) if isinstance(source, list) else bool(source)
    if not ok:
        return ["No real image found (gradient fallback) - not publishable"]
    return []


def generate_review(brief, render, photo_zone_ratio, settings=None):
    """Mechanical PASS/FAIL for one post, plus an automated Gemini vision/copy-
    accuracy check when settings.review.gemini_api_key is configured. Without a
    key, ai_verdict/ai_notes stay null - the review-post skill (a human/vision
    agent) fills them in after actually looking at the PNG."""
    image_path = (render or {}).get("output_path")
    image_issues = check_image_quality(image_path) if image_path and Path(image_path).exists() else ["Image file not found"]
    if image_path and Path(image_path).exists():
        image_issues += check_face_in_panel(image_path, photo_zone_ratio)
    image_issues += check_has_real_image(render)
    copy_issues = check_copy_quality(brief)
    brand_issues = check_brand_compliance(brief)

    all_issues = image_issues + copy_issues + brand_issues
    mechanical_status = "PASS" if not all_issues else "FAIL"

    ai_verdict, ai_notes = None, None
    if mechanical_status == "PASS":
        # No point spending an API call on a post already mechanically rejected.
        ai_verdict, ai_notes = run_gemini_check(brief, image_path, settings)

    return {
        "article_id": brief.get("article_id", "unknown"),
        "title": brief.get("source_title", "")[:60],
        "image_path": str(image_path) if image_path else None,
        "mechanical_status": mechanical_status,
        "issues": all_issues,
        "ai_verdict": ai_verdict,   # PASS | FAIL | None (None = no Gemini key / unavailable)
        "ai_notes": ai_notes,
        "reviewed_at": datetime.now().isoformat(),
    }


def main():
    settings, brand, root = load_config()
    data_dir = root / settings["output"]["data_dir"]
    retry_limit = settings["posting"]["retry_limit"]
    photo_zone_ratio = brand["panel_layout"]["photo_zone_ratio"]

    copy_path = data_dir / "copy.json"
    manifest_path = data_dir / "render_manifest.json"

    if not copy_path.exists():
        print("copy.json not found.")
        return

    with open(copy_path) as f:
        copy_data = json.load(f)

    rendered_map = {}
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = json.load(f)
        for r in manifest.get("rendered", []):
            rendered_map[r["article_id"]] = r

    print(f"Mechanical pre-filter: {len(copy_data['briefs'])} posts (max {retry_limit} retries)...")

    reviews = []
    pass_count = 0
    fail_count = 0

    for brief in copy_data["briefs"]:
        article_id = brief.get("article_id", "unknown")
        render = rendered_map.get(article_id)

        review = generate_review(brief, render, photo_zone_ratio, settings)
        reviews.append(review)

        if review["mechanical_status"] == "PASS":
            pass_count += 1
            print(f"  PASS: {review['title']}")
        else:
            fail_count += 1
            print(f"  FAIL: {review['title']}")
            for issue in review["issues"]:
                print(f"     -> {issue}")

        if review["ai_verdict"]:
            print(f"     Gemini: {review['ai_verdict']} - {review['ai_notes']}")

    ai_pass_count = sum(1 for r in reviews if r["ai_verdict"] == "PASS")
    ai_fail_count = sum(1 for r in reviews if r["ai_verdict"] == "FAIL")

    output = {
        "reviewed_at": datetime.now().isoformat(),
        "summary": {
            "total": len(reviews),
            "mechanical_passed": pass_count,
            "mechanical_failed": fail_count,
            "ai_passed": ai_pass_count,
            "ai_failed": ai_fail_count,
            "retry_limit": retry_limit,
        },
        "reviews": reviews,
    }

    output_path = data_dir / "review.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nMechanical pre-filter done: {pass_count} passed, {fail_count} failed -> {output_path}")
    if ai_pass_count or ai_fail_count:
        print(f"Gemini check: {ai_pass_count} passed, {ai_fail_count} failed.")
    else:
        print("Next: run the review-post skill to have a vision agent judge each PNG for real "
              "(no review.gemini_api_key configured, so this ran mechanical-only).")


if __name__ == "__main__":
    main()
