---
name: write-copy
description: Generate Instagram copy (kicker, headline, subline, caption, hashtags) plus real-photo sourcing hints for filtered news stories. Reads filtered_news.json, outputs copy.json with structured briefs that YOU must fill with creative text.
version: 2.0.0
author: moatdaily
---

# Write Copy

## Objective
Create scroll-stopping Instagram copy for each selected news story. The script generates structured briefs - you fill in the creative text.

## When to Use
- After `filter-news` has run and `data/filtered_news.json` exists
- Third step of the MoatDaily pipeline

## Grounding Rule (read this first)
Every brief includes `source_title`, `source_description`, and `source_text` (the actual scraped article body, up to ~2000 characters, fetched via `scripts/fetchers.py`). **Everything you write must be traceable to one of those three fields.** Reframing, condensing, and adding your own opinionated take are fine and encouraged - inventing facts, numbers, dates, quotes, or names that aren't in the source is not. If the source doesn't give you enough to write confidently, say less rather than making something up. (`source_text` can be thin or empty for Google-News-sourced stories whose real article sits behind a JS redirect - lean harder on `source_title`/`source_description` in that case, still without inventing.)

Two more rules apply to every text field: **never use an em dash character - use a hyphen (-) instead**, and **never name the source publication** (ETtech, Bloomberg, Reuters, etc.) in the headline/subline/caption text.

## Steps
1. Run the copy brief generator:
   ```bash
   cd /Users/vipulkatarnaware/Documents/AI\ Agents/moatdaily
   python scripts/write_copy.py
   ```
2. Open `data/copy.json` - each brief has empty `text` fields you must fill
3. **FOR EACH BRIEF, fill in:**

### Kicker (`copy.kicker.text`) - optional
- A 1-3 word gray eyebrow above the headline (e.g. `FUNDING`, `AI`, `MARKETS`)
- Rendered UPPERCASE. Leave blank if it adds nothing.

### Headline (`copy.headline.text`)
- Max 12 words. The base text is **regular weight** - not all-bold.
- Wrap ONE key phrase in `**double asterisks**` - it renders bold + soft violet (the only emphasis).
- Examples:
  - `ITC launches a cola priced **6X higher** than Campa`
  - `**Sam Altman** wants to give the US a stake in OpenAI`
  - `Meghalaya just blocked **Blinkit** to protect local stores`

### Subline (`copy.subline.text`)
- 1-2 sentences (~15-30 words) that actually explain the story further
- Adds real context the headline doesn't cover - the deeper detail belongs in the caption
- Conversational tone, no `**bold**`

### Caption (`copy.caption.text`)
Follow this structure:
```
[Hook - 1 bold line, no emoji spam]

[Body - 3-5 lines explaining the news with Indian context]

[Your take - 1-2 opinionated lines to spark debate]

[CTA - Ask a question to drive comments]

---
#hashtag1 #hashtag2 ... (8-12 hashtags)

📸 Images used for editorial/educational purposes only.
```

### Assets (`assets`) - the single lever for a premium post
There is **no archetype to pick**. Every static post uses one clean editorial template, so the ONLY thing that makes a post look great is a **100%-relevant real photo**. Give the renderer good hints:
- `entities`: real named people/companies to look up (e.g. `["Indra Nooyi"]`) - used for a Wikipedia lead-image lookup. Be specific.
- `primary_query`: a TIGHT photo search query if no entity/article photo fits (e.g. `"SEBI building Mumbai"`, not `"finance"`)
- `image_url`: **if you can search/browse the web, use it now** - find the real photo directly (like a person googling the story) and put its URL here. This takes priority over everything and skips the fallback waterfall entirely. See the `select-images` skill for the full picking criteria.
- `treatment`: leave `"auto"`. The renderer auto-fits any photo (cover crop, or letterbox for off-ratio images), so real photos always sit cleanly. Only set `"cutout"` for a clean single subject (product on plain bg, well-lit portrait); it's guarded and falls back automatically.

### Carousel Slides (`copy.carousel_slides.slides`)
Only if `post_type` is "carousel":
- Array of objects: `[{"text": "Slide text with **highlights**"}, ...]`
- Slide 1 is the hook (rendered as a full post)
- Slides 2-6: one point per slide

## Brand Voice
- **Tone**: Confident, opinionated, conversational - like a smart friend sharing news
- **Audience**: Indian millennials/Gen-Z into startups, business, AI, tech
- **Language**: English, occasional Hindi words only if natural
- **Perspective**: We don't just report - we add our take

## Next Step
→ Run the `select-images` skill, then `render-post`
