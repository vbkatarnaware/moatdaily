---
name: render-post
description: Render premium Instagram posts from copy.json using a reserved-panel HTML/CSS + Playwright + Jinja2 template - photo zone on top, solid text panel on the bottom, so the subject never ends up under the headline. Free real-photo sourcing, subject-aware crop, deterministic premium finish. Outputs high-res PNG files to output/posts/YYYY-MM-DD/.
version: 4.0.0
author: moatdaily
---

# Render Post

## Objective
Turn copy briefs into premium Instagram post images. One clean template does everything - a relevant real photo carries the post, with minimal, consistent editorial styling on top.

## When to Use
- After `write-copy` has filled `copy.json`, and `select-images` has set `assets.image_url` (or left it blank for the fallback waterfall)
- Fifth-ish step of the MoatDaily pipeline

## Steps
1. Ensure `data/copy.json` has the `copy` text and `assets` hints filled
2. Run the render script:
   ```bash
   cd "/Users/vipulkatarnaware/Documents/AI Agents/moatdaily"
   source .venv/bin/activate
   python scripts/render_html.py
   ```
3. Check output at `output/posts/YYYY-MM-DD/`
4. Open each generated PNG and visually verify quality (or hand off to `review-post`)

## How Rendering Works (thin AI role, deterministic Python)
The AI never touches pixels - it only fills the small `copy` + `assets` JSON in `copy.json` (see `write-copy`) and, ideally, picks the image directly (see `select-images`). Everything else is deterministic:

- **Layout**: every static post renders `templates/archetypes/post.html`; carousels render `templates/archetypes/carousel.html`. Both share `templates/archetypes/_base.html` for brand tokens (colors, fonts, brand bar) read from `config/brand.yaml`. There is **no archetype to pick**.
- **Reserved-panel composition**: the canvas splits into a photo zone (top ~62%) and a solid text panel (bottom ~38%), with a soft feathered seam between them. The subject always lives in the photo zone; the headline always lives in the panel. They never overlap - a real photo's subject can't end up hidden under the text.
- **Image sourcing** (`scripts/assets.py`), free waterfall, stops at first success:
  1. `assets.image_url` - the agent's own direct pick (preferred - see `select-images`)
  2. The article's own `og:image` (parsed from `source_url`)
  3. Wikipedia lead image for named `assets.entities`
  4. Brave image search keyed on `assets.entities[0]` or `assets.primary_query`
  5. Branded dark gradient fallback (never a broken image)
  A photo-vs-logo guard skips flat wordmarks that a lookup sometimes returns instead of a real photo.
- **Image fit** - the renderer pre-composites every hero to exactly fill the photo zone (not the full canvas):
  - Subject-aware **cover** crop: face detection first, then visual-saliency detection, then a fixed top-weighted fallback - keeps the actual subject in frame instead of a blind center crop.
  - Source aspect ratio far off the zone ratio -> **letterbox** on brand-black (bars blend into the background) instead of an ugly crop.
  - `assets.treatment: "cutout"` -> `rembg` isolates a clean single subject, cropped to its bounding box so it fills the zone properly; guarded, and silently falls back to cover/letterbox if the cutout is poor. Don't reach for cutout by default.
- **Deterministic premium finish** (`scripts/imagefx.py`): every sourced photo gets a gentle brand-ward color grade, a light vignette, and a touch of film grain - no AI, no tokens, just the editorial texture that separates a raw sourced photo from a designed post.
- **Styling**: mixed-weight headline (base regular; one `**keyword**` bold + soft violet), an explanatory subline, an optional gray kicker, and a blended brand row (accent line + handle) at the bottom of the panel. Deliberately minimal - the photo does the work.
- **Fonts**: bundled Inter TTFs embedded as data URIs (`@font-face`), so rendering is deterministic and works fully offline.

## Visual Design Spec
- **Engine**: Playwright headless Chromium (HTML/CSS layout) + Jinja2 templating
- **Canvas**: 1080x1350px (4:5) for both static posts and carousel slides
- **Brand**: near-black (`#0A0A0A`) + a tiny amount of Electric Violet (`#8B5CF6`), Inter typography

## If the Sourced Image Is Still Poor or Irrelevant
Relevance is the whole game. If the waterfall returns something off:
1. Run (or re-run) the `select-images` skill - search the web directly and put a better, directly-relevant real-photo URL in `data/copy.json` -> `assets.image_url` (highest priority), or tighten `assets.entities` / `assets.primary_query`
2. Re-run the render script

## Next Step
→ Run the `review-post` skill
