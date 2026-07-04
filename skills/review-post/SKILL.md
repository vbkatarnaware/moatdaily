---
name: review-post
description: Quality gate - a mechanical pre-filter script catches objective defects (size, corruption, copy length, disclaimer, em dashes), then YOU (a vision-capable agent) actually look at each rendered PNG and judge relevance, readability, and premium feel. Max 3 retries on failure. Outputs/updates review.json.
version: 2.0.0
author: moatdaily
---

# Review Post

## Objective
Ensure every post meets quality standards before it's ready to publish. This is a two-part gate: code catches what code can reliably catch; you catch what only a human eye (or a vision-capable agent) can catch. Don't skip your half - the mechanical script cannot tell you if a post looks good.

## When to Use
- After `render-post` has produced PNG files
- Sixth-ish step of the MoatDaily pipeline

## Step 1 - Mechanical Pre-Filter (script)
```bash
cd "/Users/vipulkatarnaware/Documents/AI Agents/moatdaily"
source .venv/bin/activate
python scripts/review_post.py
```
This writes `data/review.json` with one entry per post: `mechanical_status` (PASS/FAIL) and `issues` (size not 4:5, corrupt/blank image, missing/too-long copy, no hashtags, missing disclaimer, a stray em dash, or - as a structural safety net - a detected face overlapping the text panel). `ai_verdict` and `ai_notes` start as `null` - that's your job, next.

If `mechanical_status` is FAIL, fix the listed issue first (usually a `copy.json` edit) before spending time on the visual check.

## Step 2 - Visual Review (you, actually looking at the image)
For each post whose `mechanical_status` is PASS, open the actual PNG at its `image_path` and judge it against this checklist:

- **Relevance**: is the photo genuinely about THIS story - the right person, company, place, or event? Not a generic stand-in.
- **Composition**: is the subject fully visible and well-placed within the photo zone (top ~62% of the frame)? Not awkwardly cropped, not cut off mid-face.
- **Readability**: is the headline clearly legible against the panel? Does the feathered seam between photo and panel look intentional, not like a glitch?
- **Premium feel**: would this hold up next to Marketing Mind, 101xf, or Marketing Maverick? Or does it look like a rough draft?
- **Brand consistency**: brand name top-right, accent line + handle at the bottom of the panel, exactly one highlighted keyword in violet in the headline.
- **No foreign watermark/logo**: does the hero photo itself carry another outlet's logo, masthead, or watermark anywhere in the frame (e.g. a publisher's bubble logo baked into a corner)? This is a hard FAIL regardless of how the image was sourced, including a trusted `image_url` override that skipped mechanical checks - the vision check is the only thing catching this case, so look carefully at every corner of the photo zone.
- **Carousel-specific**: for `carousel` posts, is each slide's image actually different and relevant to that specific slide's fact (not the same photo repeated across all slides, unless the source genuinely offers only one visual and that was a deliberate choice)?

Write your verdict back into that post's entry in `data/review.json`:
- `"ai_verdict": "PASS"` or `"ai_verdict": "FAIL"`
- `"ai_notes": "..."` - if FAIL, the specific fix needed (e.g. "photo is a Nithin Kamath quote card, not Nithin Kamath himself - re-pick via select-images")

## On FAIL (mechanical or visual)
1. Identify the specific issue.
2. Fix it at the right layer:
   - Wrong/generic/irrelevant photo -> re-run `select-images` (pick a better `assets.image_url`), then re-render
   - Copy too long/short, missing disclaimer, em dash -> edit `data/copy.json`, then re-render
   - Structural (face overlapping panel, wrong size) -> re-render; if it persists, it's a template bug, not a content fix
3. Re-run `render-post` then `review-post`.
4. **Max 3 retries total.** If still failing, flag for human review rather than publishing a weak post.

## Next Step
→ Run the `log-post` skill (and `publish-post` once Instagram credentials are configured)
