import base64
import json
import os
import re
from datetime import datetime
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

import assets
import sanitize

ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = ROOT / "templates" / "archetypes"

POST_SIZE = (1080, 1350)      # single static post - 4:5
CAROUSEL_SIZE = (1080, 1350)  # carousel slides - also 4:5


def load_config():
    with open(ROOT / "config" / "settings.yaml") as f:
        settings = yaml.safe_load(f)
    with open(ROOT / "config" / "brand.yaml") as f:
        brand = yaml.safe_load(f)
    return settings, brand


def process_markdown_bold(text):
    """Converts **text** to a violet inline span (the headline emphasis)."""
    text = sanitize.clean_text(text)
    return re.sub(r"\*\*(.*?)\*\*", r'<span class="highlight">\1</span>', text)


def font_data_uri(path):
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:font/ttf;base64,{encoded}"


def load_fonts():
    return {
        "font_regular_uri": font_data_uri(ROOT / "templates" / "fonts" / "Inter-Regular.ttf"),
        "font_bold_uri": font_data_uri(ROOT / "templates" / "fonts" / "Inter-Bold.ttf"),
        "font_black_uri": font_data_uri(ROOT / "templates" / "fonts" / "Inter-Black.ttf"),
    }


def panel_geometry(brand, height):
    """Split the canvas into the photo zone (top) and the reserved text panel (bottom)."""
    pl = brand["panel_layout"]
    photo_zone_h = round(height * pl["photo_zone_ratio"])
    return {
        "photo_zone_h": photo_zone_h,
        "panel_h": height - photo_zone_h,
        "feather_px": pl["feather_px"],
        "panel_bg": pl["panel_bg"],
    }


def base_context(brand, width, height, fonts):
    ctx = {
        "width": width,
        "height": height,
        "colors": brand["colors"],
        "brand": brand["brand"],
        "components": brand["components"],
        **fonts,
    }
    ctx.update(panel_geometry(brand, height))
    return ctx


def resolve_treatment(assets_spec):
    """Direct embed (cover/letterbox) is ALWAYS the default. Cutout only on explicit opt-in."""
    requested = (assets_spec or {}).get("treatment", "auto")
    return "cutout" if requested == "cutout" else "fullbleed"


def render_via_playwright(page, html_content, output_png_path, width, height):
    temp_html_path = os.path.abspath(f"data/temp_{os.path.basename(output_png_path)}.html")
    with open(temp_html_path, "w") as f:
        f.write(html_content)
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"file://{temp_html_path}")
    page.wait_for_load_state("networkidle")
    page.screenshot(path=output_png_path)
    os.remove(temp_html_path)


def resolve_hero_for_zone(assets_spec, source_url, treatment, width, height, brand, settings, source_image_url=None):
    """Resolve the hero image sized to fill the PHOTO ZONE (not the full canvas)."""
    it = brand["image_treatment"]
    geom = panel_geometry(brand, height)
    return assets.resolve_hero_image(
        assets_spec,
        source_url,
        treatment,
        width,
        geom["photo_zone_h"],
        cover_tolerance=it.get("cover_tolerance", 0.85),
        letterbox_bg=it.get("letterbox_bg", "#0A0A0A"),
        source_image_url=source_image_url,
        brave_api_key=settings["news"].get("brave_api_key"),
        finish_opts=brand.get("image_finish"),
    )


def build_post_context(brief, brand, fonts, width, height, settings):
    assets_spec = brief.get("assets", {})
    treatment = resolve_treatment(assets_spec)

    hero = resolve_hero_for_zone(
        assets_spec, brief.get("source_url"), treatment, width, height, brand, settings,
        source_image_url=brief.get("source_image_url"),
    )

    ctx = base_context(brand, width, height, fonts)
    ctx.update({
        "hero": hero,
        "kicker": sanitize.clean_text(brief.get("copy", {}).get("kicker", {}).get("text", "")),
        "headline_html": process_markdown_bold(brief["copy"]["headline"]["text"]),
        "subline": sanitize.clean_text(brief["copy"]["subline"]["text"]),
    })
    return ctx


def main():
    settings, brand = load_config()
    fonts = load_fonts()

    with open("data/copy.json", "r") as f:
        data = json.load(f)

    # Stamp the disclaimer onto each caption now, at render time, so it's already
    # present for review_post.py's check and every downstream stage - never a
    # separate step that could be skipped.
    for brief in data["briefs"]:
        caption = brief["copy"]["caption"]
        caption["text"] = sanitize.ensure_disclaimer(caption["text"])
    with open("data/copy.json", "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    date_str = datetime.now().strftime("%Y-%m-%d")
    out_dir = f"output/posts/{date_str}"
    os.makedirs(out_dir, exist_ok=True)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

    print(f"🎨 Rendering {len(data['briefs'])} posts...")

    rendered = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for brief in data["briefs"]:
            post_type = brief.get("post_type", "static")
            article_id = brief["article_id"]
            title = brief["source_title"][:50]
            print(f"  → Rendering [{post_type}]: {title}...")

            post_files = []
            image_source = None

            if post_type == "carousel":
                slides = brief["copy"]["carousel_slides"]["slides"]
                template = env.get_template("carousel.html")
                width, height = CAROUSEL_SIZE

                brief_assets_spec = brief.get("assets", {})
                slide_specs = brief_assets_spec.get("slides") or []

                image_sources = []
                hero_cache = {}

                for j, slide in enumerate(slides):
                    # Each slide gets its own hero image when the agent/gatherer supplied one;
                    # fall back to the brief-level image only for thin sources with just one photo.
                    slide_spec = slide_specs[j] if j < len(slide_specs) else {}
                    assets_spec = slide_spec if (slide_spec or {}).get("image_url") else brief_assets_spec

                    cache_key = assets_spec.get("image_url") or id(assets_spec)
                    if cache_key not in hero_cache:
                        hero_cache[cache_key] = resolve_hero_for_zone(
                            assets_spec, brief.get("source_url"), resolve_treatment(assets_spec), width, height,
                            brand, settings, source_image_url=brief.get("source_image_url"),
                        )
                    hero = hero_cache[cache_key]
                    image_sources.append(hero.get("source"))

                    ctx = base_context(brand, width, height, fonts)
                    ctx.update({
                        "hero": hero,
                        "current_slide": j + 1,
                        "total_slides": len(slides),
                        "text_html": process_markdown_bold(slide["text"]),
                    })
                    html_content = template.render(**ctx)
                    out_path = f"{out_dir}/{article_id}_slide_{j + 1}.png"
                    render_via_playwright(page, html_content, out_path, width, height)
                    post_files.append(out_path)

                image_source = image_sources
            else:
                template = env.get_template("post.html")
                width, height = POST_SIZE
                ctx = build_post_context(brief, brand, fonts, width, height, settings)
                image_source = ctx["hero"].get("source")
                html_content = template.render(**ctx)
                out_path = f"{out_dir}/{article_id}_static.png"
                render_via_playwright(page, html_content, out_path, width, height)
                post_files.append(out_path)

            rendered.append({
                "article_id": article_id,
                "post_type": post_type,
                "output_path": post_files[0],
                "files": post_files,
                "image_source": image_source,  # which waterfall step supplied the hero image
                "rendered_at": datetime.now().isoformat(),
            })

        browser.close()

    with open("data/render_manifest.json", "w") as f:
        json.dump({"rendered": rendered, "output_dir": out_dir}, f, indent=2)

    print(f"\n✅ Rendered {len(rendered)} posts to {out_dir}")


if __name__ == "__main__":
    main()
