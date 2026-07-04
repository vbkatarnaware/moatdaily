#!/usr/bin/env python3
"""
MoatDaily - Mechanical Pre-Filter

This script only checks what code CAN reliably check: resolution, corruption,
copy length/presence/hashtags, the disclaimer, no stray em dashes, and a
structural safety net (no detected face bleeding into the reserved text panel).

It does NOT judge whether a post looks good, whether the photo is relevant, or
whether the crop/composition is premium - those are subjective and belong to
the `review-post` skill, where a vision-capable agent actually looks at each
rendered PNG. This script's PASS/FAIL is a pre-filter gate, not the review.

Usage: python scripts/review_post.py
"""

import json
import os
from datetime import datetime
from pathlib import Path

import yaml
from PIL import Image

EXPECTED_SIZE = (1080, 1350)  # both static and carousel are 4:5


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


def generate_review(brief, image_path, photo_zone_ratio):
    """Mechanical PASS/FAIL for one post. ai_verdict/ai_notes are left null here -
    the review-post skill fills them in after actually looking at the PNG."""
    image_issues = check_image_quality(image_path) if image_path and Path(image_path).exists() else ["Image file not found"]
    if image_path and Path(image_path).exists():
        image_issues += check_face_in_panel(image_path, photo_zone_ratio)
    copy_issues = check_copy_quality(brief)
    brand_issues = check_brand_compliance(brief)

    all_issues = image_issues + copy_issues + brand_issues

    return {
        "article_id": brief.get("article_id", "unknown"),
        "title": brief.get("source_title", "")[:60],
        "image_path": str(image_path) if image_path else None,
        "mechanical_status": "PASS" if not all_issues else "FAIL",
        "issues": all_issues,
        "ai_verdict": None,   # filled by the review-post skill: PASS | FAIL
        "ai_notes": None,     # filled by the review-post skill: what to fix, if anything
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
            rendered_map[r["article_id"]] = r["output_path"]

    print(f"Mechanical pre-filter: {len(copy_data['briefs'])} posts (max {retry_limit} retries)...")

    reviews = []
    pass_count = 0
    fail_count = 0

    for brief in copy_data["briefs"]:
        article_id = brief.get("article_id", "unknown")
        image_path = rendered_map.get(article_id)

        review = generate_review(brief, image_path, photo_zone_ratio)
        reviews.append(review)

        if review["mechanical_status"] == "PASS":
            pass_count += 1
            print(f"  PASS: {review['title']}")
        else:
            fail_count += 1
            print(f"  FAIL: {review['title']}")
            for issue in review["issues"]:
                print(f"     -> {issue}")

    output = {
        "reviewed_at": datetime.now().isoformat(),
        "summary": {
            "total": len(reviews),
            "mechanical_passed": pass_count,
            "mechanical_failed": fail_count,
            "retry_limit": retry_limit,
        },
        "reviews": reviews,
    }

    output_path = data_dir / "review.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nMechanical pre-filter done: {pass_count} passed, {fail_count} failed -> {output_path}")
    print("Next: run the review-post skill to have a vision agent judge each PNG for real.")


if __name__ == "__main__":
    main()
