---
name: select-images
description: Pick the single most relevant, best-quality real photo for each post - either directly from the web (primary) or from a gathered candidate set (fallback). Writes the chosen URL into copy.json as assets.image_url. This is the step that fixes "wrong/irrelevant image" problems - use your actual vision/search ability here, don't skip it to save tokens.
version: 1.0.0
author: moatdaily
---

# Select Images

## Objective
Every post needs ONE real photo that is 100% relevant to its headline, sits well in the photo zone, and won't look cheap once cropped. This is the single highest-leverage step for post quality - use your web/image search and vision ability fully here.

## When to Use
- After `write-copy` has filled `copy.json` with headline/subline/assets hints (entities, primary_query)
- Before `render-post`
- Fifth-ish step, but it can run for either `static` or `carousel` briefs

## Unattended runs (no vision/search model - e.g. free-tier text-only)
If you can't browse or see images, **skip this step entirely** - do not guess a
URL. Leave `assets.image_url` blank and let `render_html.py` auto-select: its
`assets.resolve_hero_image` heuristic searches by `entities`/`primary_query` and
picks a real, non-logo photo mechanically. Slightly lower quality than a vision
pick but reliable and zero tokens. Only do Path A/B when you actually have
vision + web search.

## Path A - Direct (preferred, use this whenever you can browse/search the web)
Do what a person would do: search the web/images for the story (use the headline, `assets.entities`, or `assets.primary_query` as your query), open a few results, and pick the photo that is **actually about this story** - the right person, the right company, the right event. Then:

1. Write that photo's direct URL into `data/copy.json` → `assets.image_url` for that `article_id`.
2. Done - skip Path B entirely for this brief. `render_html.py` will use your URL as-is (it's the top-priority source in the sourcing waterfall).

### Carousels: pick ONE image PER SLIDE, not one for the whole post
For `post_type: "carousel"` briefs, `assets.slides` is a parallel array - one entry per `copy.carousel_slides.slides` entry, same order. Search and pick a distinct, relevant photo for **each slide** based on that specific slide's fact (slide 1's hook, slide 2's specific data point, etc.), and write each into `assets.slides[i].image_url`. Do not paste the same URL into every slide - a carousel where every frame shows the identical photo reads as lazy and undermines the "swipe for more" format. The only exception is when the underlying story genuinely has just one available visual and multiple slides are pure text callouts about that same fact - even then, treat it as a deliberate exception, not the default.

Do not take the first image search result blindly - open it and confirm it's the right subject before committing the URL. A wrong photo (wrong person, a logo, a screenshot, a stock photo) is worse than no photo (the renderer's branded fallback looks intentional; a wrong photo looks broken).

## Path B - Fallback (no browsing available, or you skipped a pick)
If you can't browse the web directly, run the deterministic gatherer, which walks a free-source waterfall (the brief's own image, article `og:image`, Wikipedia lead image for named entities, Brave image search) and collects up to 5 real-photo candidates per brief as small thumbnails:

```bash
cd "/Users/vipulkatarnaware/Documents/AI Agents/moatdaily"
source .venv/bin/activate
python scripts/gather_images.py
```

This writes `data/image_candidates.json`. It skips any brief (or, for carousels, any slide) where `assets.image_url` (or `assets.slides[i].image_url`) is already set (Path A already handled it).

For a `static` item in `image_candidates.json` (a flat `candidates` list):
1. Look at the `thumbnail_data_uri` of each candidate (small JPEGs - cheap to view, a handful per post).
2. Judge each against the `headline`: is this the right person/company/place/event? Is it a real photo (not a logo, not a screenshot, not obviously unrelated, no foreign watermark)?
3. Pick the best candidate and write its `url` into `data/copy.json` → the matching brief's `assets.image_url`.
4. If NONE of the candidates are good enough, leave `assets.image_url` blank. The renderer falls back to a clean branded gradient - that looks intentional. A wrong photo does not.

For a `carousel` item (a `slides: [{slide_index, candidates}]` list): repeat the same judgment **per slide**, writing each pick into `assets.slides[slide_index].image_url`. Judge each slide's candidates against that slide's own text, not the overall headline - a slide about a specific number or company needs a photo of that specific thing, not a repeat of slide 1's hero. Leave a slide's `image_url` blank (falls back to the brief-level image) only if that slide truly has no good distinct candidate.

## What Makes a Photo Good Here
- **Relevance first, always.** The exact subject named in the headline, not "someone in a suit" or "a generic office."
- **Real photo, not a graphic.** No logos, wordmarks, screenshots-of-text, or infographics.
- **No foreign branding baked into the image, ever.** Reject any candidate that carries a visible watermark, masthead, or logo from the source publication or any third-party media company - a small "StartupTalky"/"ETtech"/etc. bubble logo in a corner, a Getty/press-agency watermark, a corporate logo stamp the publisher added as attribution. This applies even when the rest of the image is a legitimate, well-composed photo or graphic - one foreign logo is enough to reject it. This is a different, stricter check than "no logos/infographics" above: that line is about images that ARE a logo; this line is about otherwise-good images that CARRY someone else's logo. The only branding a MoatDaily post should ever show is MoatDaily's own, added by the renderer. (Incidental real-world branding that's just part of the scene - a person's own shirt logo, a building's signage in a genuine photograph - is fine; the concern is source-attribution branding the publisher stamped on, not scene content.)
- **Composition-aware**: the renderer places this in a landscape-ish photo zone (roughly 4:3-ish, wider than the full 4:5 canvas) above a solid text panel - a photo with the subject centered or slightly high, with some headroom, crops better than an extreme close-up or a photo where the subject already touches the frame edges.
- **Resolution**: prefer larger images. A tiny thumbnail will look soft once it fills 1080px of width.

## Next Step
→ Run the `render-post` skill (it will resolve, crop, and premium-finish whatever `assets.image_url` you set - or the fallback waterfall if you left it blank).
