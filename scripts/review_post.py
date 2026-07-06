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
automatically (escalating to review.openrouter_api_key as a last resort if the
free tier is quota-exhausted - see run_gemini_check). A live AI verdict is
mandatory to publish: publish_instagram.py re-runs this check itself and skips
a post rather than publish on mechanical_status alone if no verdict is
available on any path.

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
- Identity: if the headline/subline/caption names a specific person, is the person in the photo VERIFIABLY that person? Judge this ONLY from your own independent knowledge of what that named person looks like - do NOT treat the headline/kicker/caption text rendered into the image itself as evidence, since that text was written by an automated pipeline and may be attached to the wrong photo. If you do not have confident independent knowledge of this specific person's face, or cannot verify the match, treat it as a FAIL - do not guess or give the benefit of the doubt.
- Relevance: is the photo genuinely about THIS story - the right person, company, place, or event? Not a generic stand-in.
- Composition: is the subject fully visible and well-placed within the photo zone (top ~62% of the frame)? Not awkwardly cropped or cut off mid-face.
- No foreign watermark/logo: does the hero photo carry another outlet's logo, masthead, or watermark anywhere in the frame? Hard FAIL if so, regardless of how the image was sourced.
- Copy accuracy: does the headline/subline/caption below invent any fact, number, date, quote, or name that is NOT present in the source text below? Hard FAIL if so.

When uncertain on any item, FAIL. A wrongly rejected post is simply replaced by the next
candidate; a wrongly approved post publishes a real mistake. Bias every judgment call toward
FAIL, not PASS.

Post headline: {headline}
Post subline: {subline}
Post caption: {caption}

Source title: {source_title}
Source description: {source_description}
Source text: {source_text}

Respond with JSON: {{"verdict": "PASS" or "FAIL", "notes": "one sentence explaining why"}}"""

GEMINI_GENERATION_CONFIG = {
    # Deterministic judging: the exact same image+prompt must yield the exact
    # same verdict every time (observed directly - the same wrong-person photo
    # FAILed once and PASSed on a later, otherwise-identical call at default
    # sampling). temperature=0 + a fixed seed removes that randomness.
    "temperature": 0.0,
    "top_p": 1.0,
    "seed": 7,
}


def _strip_json_fence(text):
    """gemini-2.5-flash (unlike the primary model) sometimes wraps its JSON
    response in a markdown code fence even when response_format requests raw
    JSON - observed directly: identical verdict/notes content, just wrapped in
    ```json ... ```. Strip that wrapper before parsing."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def _is_quota_error(e):
    """True only for a genuine Gemini free-tier quota/rate exhaustion (observed directly
    as a 429 RateLimitError with body {"code": "too_many_requests", ...}) - the one and
    only condition allowed to escalate to the paid OpenRouter fallback. Any other failure
    (network blip, bad response shape, missing SDK) must NOT escalate - it degrades to
    mechanical-only, same as before OpenRouter existed."""
    if getattr(e, "status_code", None) == 429:
        return True
    msg = str(e).lower()
    return "too_many_requests" in msg or "quota" in msg or " 429" in msg or "429 " in msg


def _judge(call_once, model, trust_single):
    """Shared verdict logic for one model. trust_single=True (the direct primary only):
    one call is trusted directly - observed directly that temperature=0 + a fixed seed
    makes its verdict reproducible call-to-call. trust_single=False (every other model -
    direct fallbacks and all OpenRouter models): fail-closed 2-call consensus, since a
    fallback-grade model's verdict was observed NOT to be reproducible even at the same
    temperature=0/seed config (PASS/FAIL/PASS across 3 identical calls on the same image).
    A PASS needs both calls to agree; any FAIL or disagreement fails closed to FAIL rather
    than risk a wrong-image publish on a coin-flip verdict. Exceptions from call_once
    propagate so the caller can distinguish quota errors from other failures."""
    verdict, notes = call_once(model)
    if trust_single:
        return verdict, notes

    verdict2, notes2 = call_once(model)
    if verdict == "PASS" and verdict2 == "PASS":
        return "PASS", notes
    return "FAIL", (notes if verdict == "FAIL" else notes2) or \
        "Fallback model verdict inconsistent across repeated checks - failing closed."


def _run_gemini_direct(prompt, image_path, review_cfg):
    """The direct google-genai SDK path (free tier). Returns (verdict, notes, quota_hit) -
    quota_hit is True only when an attempt failed specifically due to free-tier quota
    exhaustion, which is the sole trigger for escalating to the paid OpenRouter fallback."""
    api_key = (review_cfg.get("gemini_api_key") or "").strip()
    if not api_key:
        return None, None, False

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None, None, False

    models = [review_cfg.get("gemini_model") or "gemini-3.5-flash"]
    models += list(review_cfg.get("gemini_fallback_models") or [])

    try:
        # Explicit timeout: a hung network call here (observed directly - an SDK
        # call with no timeout blocked for 6+ minutes on a transient network blip)
        # would otherwise stall review_post.py and, since publish_instagram.py
        # also calls this function, the publish stage too.
        client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS))
        uploaded = client.files.upload(file=str(image_path))
    except Exception as e:
        print(f"[WARN] Gemini file upload failed: {e}")
        return None, None, _is_quota_error(e)

    def call_once(model):
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
            generation_config=GEMINI_GENERATION_CONFIG,
        )
        result = json.loads(_strip_json_fence(interaction.output_text))
        verdict = result.get("verdict")
        if verdict not in ("PASS", "FAIL"):
            raise ValueError(f"unexpected verdict field: {result!r}")
        return verdict, result.get("notes")

    quota_hit = False
    for i, model in enumerate(models):
        try:
            verdict, notes = _judge(call_once, model, trust_single=(i == 0))
            return verdict, notes, False
        except Exception as e:
            print(f"[WARN] Gemini check failed on {model}: {e}")
            quota_hit = quota_hit or _is_quota_error(e)
            continue

    return None, None, quota_hit


def _openrouter_call_once(model, prompt, data_uri, api_key):
    import requests

    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }],
            "temperature": 0,
            "response_format": {"type": "json_object"},
            # Without an explicit cap, OpenRouter defaults to the model's max (65536 for
            # gemini-3.5-flash) and 402s if the account's credit balance can't cover the
            # theoretical max - observed directly. The actual response is a one-line JSON
            # verdict/notes; 2000 leaves generous headroom over that plus any thinking
            # tokens while staying well inside a small credit balance.
            "max_tokens": 2000,
        },
        timeout=GEMINI_TIMEOUT_MS / 1000,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    result = json.loads(_strip_json_fence(content))
    verdict = result.get("verdict")
    if verdict not in ("PASS", "FAIL"):
        raise ValueError(f"unexpected verdict field: {result!r}")
    return verdict, result.get("notes")


def _run_openrouter(prompt, image_path, review_cfg):
    """Last-resort fallback - ONLY reached from run_gemini_check when the direct Gemini
    free tier is quota-exhausted. Paid via the user's own OpenRouter credits, so
    deliberately restricted to Gemini models only (google/gemini* slugs); anything else
    configured is skipped with a warning rather than silently used."""
    api_key = (review_cfg.get("openrouter_api_key") or "").strip()
    if not api_key:
        return None, None

    configured = list(review_cfg.get("openrouter_models") or [])
    models = [m for m in configured if m.startswith("google/gemini")]
    for m in configured:
        if m not in models:
            print(f"[WARN] Ignoring non-Gemini OpenRouter model {m!r} - OpenRouter fallback is Gemini-only")
    if not models:
        return None, None

    try:
        import base64
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        mime = "image/png" if str(image_path).lower().endswith(".png") else "image/jpeg"
        data_uri = f"data:{mime};base64,{b64}"
    except Exception as e:
        print(f"[WARN] OpenRouter image encode failed: {e}")
        return None, None

    for model in models:
        try:
            # trust_single=False: a different backend from the direct primary, so treat
            # it as fallback-grade (2-call consensus) rather than trusting one call.
            return _judge(
                lambda m: _openrouter_call_once(m, prompt, data_uri, api_key),
                model,
                trust_single=False,
            )
        except Exception as e:
            print(f"[WARN] OpenRouter Gemini check failed on {model}: {e}")
            continue

    return None, None


def run_gemini_check(brief, image_path, settings):
    """Automated stand-in for review-post skill Step 2 (vision + copy-accuracy).

    Returns (verdict, notes) - verdict is "PASS"/"FAIL", or None if unavailable.
    Tries the direct Gemini free tier first (review.gemini_api_key). Only when that
    fails specifically due to quota exhaustion (never for any other reason) does it
    escalate to a paid OpenRouter Gemini fallback (review.openrouter_api_key) - a
    last resort so the identity/copy-accuracy check keeps running on a heavy day
    instead of silently degrading to mechanical-only. No key(s) configured, or every
    attempt unavailable for a non-quota reason, returns (None, None) - "skip", never
    "FAIL" - so an outage degrades to mechanical-only behavior, not a block on every post.
    """
    if not image_path or not Path(image_path).exists():
        return None, None

    review_cfg = (settings or {}).get("review", {}) or {}
    copy = brief.get("copy", {})
    prompt = GEMINI_PROMPT_TEMPLATE.format(
        headline=copy.get("headline", {}).get("text", ""),
        subline=copy.get("subline", {}).get("text", ""),
        caption=copy.get("caption", {}).get("text", ""),
        source_title=brief.get("source_title", ""),
        source_description=brief.get("source_description", ""),
        source_text=brief.get("source_text", ""),
    )

    verdict, notes, quota_hit = _run_gemini_direct(prompt, image_path, review_cfg)
    if verdict is not None:
        return verdict, notes

    if quota_hit:
        verdict, notes = _run_openrouter(prompt, image_path, review_cfg)
        if verdict is not None:
            return verdict, notes

    return None, None

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
    accuracy check via run_gemini_check when settings.review.gemini_api_key is
    configured. ai_verdict/ai_notes stay null if no verdict is available on any
    path (see run_gemini_check) - publish_instagram.py treats that as
    unpublishable rather than falling back to mechanical_status alone."""
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
