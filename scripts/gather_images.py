#!/usr/bin/env python3
"""
MoatDaily - Image Candidate Gathering (fallback path)

The PRIMARY way MoatDaily finds a relevant photo is the agent doing it directly:
Hermes (or any CLI agent with web/image search) googles the story like a person
would, picks the correct real photo, and writes its URL into assets.image_url.
That is the most human-like, most reliable path and needs no extra API key.

This script exists for the FALLBACK case - no browsing agent available, or the
agent didn't supply a direct pick. It gathers a handful of real-photo candidates
(never just the first hit) from free/cheap sources and writes small thumbnails
to data/image_candidates.json so a vision-capable agent (the select-images
skill) - or a human - can look at them and choose the best one, instead of the
pipeline blindly taking whatever resolves first.

Usage: python scripts/gather_images.py
"""

import io
import json
from pathlib import Path

import yaml
from PIL import Image

import assets

ROOT = Path(__file__).parent.parent
MAX_CANDIDATES = 5
THUMBNAIL_SIZE = 240


def load_config():
    with open(ROOT / "config" / "settings.yaml") as f:
        settings = yaml.safe_load(f)
    return settings


def make_thumbnail(image_bytes, max_size=THUMBNAIL_SIZE):
    """Small JPEG data URI - cheap enough for a vision agent to look at several per post."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img.thumbnail((max_size, max_size))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        return assets.to_data_uri(buf.getvalue(), "image/jpeg")
    except Exception:
        return None


def gather_candidates_for_spec(assets_spec, source_url, source_image_url, brave_api_key, max_candidates=MAX_CANDIDATES):
    """Returns None if the agent already supplied a direct pick (nothing to gather),
    otherwise a list of {url, source, thumbnail_data_uri} candidates."""
    if (assets_spec.get("image_url") or "").strip():
        return None

    candidates = []
    seen_urls = set()
    for url, label, trusted in assets.iter_image_candidates(
        assets_spec, source_url, source_image_url, brave_api_key
    ):
        if len(candidates) >= max_candidates or url in seen_urls:
            continue
        seen_urls.add(url)

        raw = assets.download_image_bytes(url)
        if not raw:
            continue
        if not trusted and not assets._is_probably_photo(raw):
            continue  # flat logo/wordmark, not a real photo

        thumb = make_thumbnail(raw)
        if not thumb:
            continue
        candidates.append({"url": url, "source": label, "thumbnail_data_uri": thumb})

    return candidates


def gather_candidates_for_brief(brief, brave_api_key, max_candidates=MAX_CANDIDATES):
    """Back-compat wrapper: gathers for the brief-level assets spec (static posts)."""
    return gather_candidates_for_spec(
        brief.get("assets", {}), brief.get("source_url"), brief.get("source_image_url"),
        brave_api_key, max_candidates,
    )


def main():
    settings = load_config()
    brave_api_key = settings["news"].get("brave_api_key")

    copy_path = ROOT / "data" / "copy.json"
    if not copy_path.exists():
        print("Error: data/copy.json not found. Run write_copy.py first.")
        return

    with open(copy_path) as f:
        data = json.load(f)

    items = []
    for brief in data["briefs"]:
        article_id = brief["article_id"]
        is_carousel = brief.get("post_type") == "carousel"
        slide_specs = (brief.get("assets", {}) or {}).get("slides") or []

        if is_carousel and slide_specs:
            slides_out = []
            for j, slide_spec in enumerate(slide_specs):
                candidates = gather_candidates_for_spec(
                    slide_spec, brief.get("source_url"), brief.get("source_image_url"), brave_api_key,
                )
                if candidates is None:
                    continue  # this slide already has its own image_url from the agent
                slides_out.append({"slide_index": j, "candidates": candidates})
                print(f"Gathered {len(candidates)} candidates for {article_id} slide {j}")

            if not slides_out:
                print(f"Skip {article_id}: every slide already has assets.slides[i].image_url set")
                continue

            items.append({
                "article_id": article_id,
                "headline": brief.get("copy", {}).get("headline", {}).get("text") or brief.get("source_title", ""),
                "post_type": "carousel",
                "slides": slides_out,
            })
            continue

        candidates = gather_candidates_for_brief(brief, brave_api_key)
        if candidates is None:
            print(f"Skip {article_id}: assets.image_url already set by the agent")
            continue

        print(f"Gathered {len(candidates)} candidates for {article_id}")
        items.append({
            "article_id": article_id,
            "headline": brief.get("copy", {}).get("headline", {}).get("text") or brief.get("source_title", ""),
            "post_type": brief.get("post_type", "static"),
            "candidates": candidates,
        })

    out_path = ROOT / "data" / "image_candidates.json"
    with open(out_path, "w") as f:
        json.dump({"items": items}, f, indent=2)

    print(f"\nWrote {len(items)} candidate set(s) to {out_path}")
    if items:
        print("Next: run the select-images skill - the agent picks the best photo per")
        print("item (or per slide, for carousels) and writes it back into copy.json.")


if __name__ == "__main__":
    main()
