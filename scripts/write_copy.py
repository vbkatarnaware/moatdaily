#!/usr/bin/env python3
"""
MoatDaily - Copy Writer (Structured Output)
Reads filtered_news.json -> generates structured copy prompts (+ scraped
source_text to ground the copy in) -> outputs copy.json

This script generates the STRUCTURE. The AI agent fills in the actual creative
copy. The script provides templates and rules the agent must follow.

Usage: python scripts/write_copy.py
"""

import json
from datetime import datetime
from pathlib import Path

import yaml

import fetchers

MAX_SOURCE_TEXT_CHARS = 2000

EM_DASH_RULE = "NEVER use an em dash character - use a hyphen (-) instead"
NO_PUBLICATION_RULE = "NEVER include news channel/publication names (like ETtech, Bloomberg, Reuters, etc.) in the headline or text."


def load_config():
    root = Path(__file__).parent.parent
    with open(root / "config" / "settings.yaml") as f:
        settings = yaml.safe_load(f)
    with open(root / "config" / "brand.yaml") as f:
        brand = yaml.safe_load(f)
    return settings, brand, root


def generate_copy_brief(article, brand):
    """Generate a structured copy brief for each article."""
    source_text = ""
    if article.get("url"):
        source_text = fetchers.fetch_article(article["url"]).get("text", "")[:MAX_SOURCE_TEXT_CHARS]

    return {
        "article_id": article["id"],
        "source_title": article["title"],
        "source_description": article["description"],
        "source_text": source_text,  # scraped article body - ground the copy in this, don't guess
        "source_url": article["url"],
        "source_image_url": article.get("image_url", ""),
        "post_type": article.get("suggested_post_type", "static"),
        "scores": article.get("scores", {}),

        "copy": {
            "kicker": {
                "text": "",  # AI fills (OPTIONAL): 1-3 word gray eyebrow above the headline
                "rules": [
                    "Optional - leave blank if it adds nothing",
                    "1-3 words, e.g. a category or source ('FUNDING', 'AI', 'MARKETS')",
                    "No punctuation - rendered UPPERCASE"
                ],
                "example": "FUNDING"
            },
            "headline": {
                "text": "",  # AI fills: max 12 words, ONE **keyword** emphasized
                "rules": [
                    "Max 12 words",
                    "Base text is regular weight - wrap ONE key phrase in **keyword** for emphasis",
                    "No clickbait - factual but punchy",
                    "Use active voice",
                    "Indian audience context",
                    "Every claim must come from source_title/source_description/source_text - reframing is fine, inventing is not",
                    EM_DASH_RULE,
                ],
                "example": "ITC launches a cola priced **6X higher** than Campa"
            },
            "subline": {
                "text": "",  # AI fills: explanatory, 2-3 lines
                "rules": [
                    "1-2 sentences (~15-30 words) that explain the story further",
                    "Adds real context the headline doesn't cover - the deeper detail goes in the caption",
                    "Conversational tone, no **bold**",
                    "Every claim must come from source_title/source_description/source_text - reframing is fine, inventing is not",
                    EM_DASH_RULE,
                    NO_PUBLICATION_RULE,
                ],
                "example": "It's a premium play aimed at the segment Reliance ignored - betting Indians will pay up for a homegrown challenger brand."
            },
            "caption": {
                "text": "",  # AI fills: Full Instagram caption
                "structure": [
                    "Hook (1 line - scroll-stopping question or bold statement)",
                    "Body (3-5 lines - explain the news, add context)",
                    "Opinion/Take (1-2 lines - opinionated angle for engagement)",
                    "CTA (1 line - ask a question to drive comments)",
                    "---",
                    "Hashtags (8-12 relevant hashtags)",
                    "Credit line: the renderer/logger appends the editorial-use disclaimer automatically - don't worry about it",
                ],
                "rules": [
                    "Max 2200 characters total",
                    "Hook must be in first line (no line break before it)",
                    "Use emojis sparingly - max 3-4",
                    "Tone: Smart friend sharing news, not news anchor",
                    "Reference Indian context where possible",
                    "Every claim must come from source_title/source_description/source_text - reframing is fine, inventing numbers/quotes/facts is not",
                    EM_DASH_RULE,
                    NO_PUBLICATION_RULE,
                ],
                "example_hook": "ITC just declared war on Reliance. And they're doing it with a ₹50 cola. 🍹"
            },
            "carousel_slides": {
                "slides": [],  # AI fills if post_type is carousel
                "rules": [
                    "Slide 1: Hook headline + hero image",
                    "Slides 2-6: One key point per slide, bold text",
                    "Last slide: Summary + CTA",
                    "Each slide: max 20 words of text",
                    "Use **bold** for keywords on each slide",
                    "Every claim must come from source_title/source_description/source_text - reframing is fine, inventing is not",
                    EM_DASH_RULE,
                    NO_PUBLICATION_RULE,
                ]
            }
        },

        "assets": {
            "image_url": "",     # AI fills: PREFERRED - search the web directly and put the real photo's URL here
            "entities": [],       # AI fills: real named people/companies to look up (e.g. ["Indra Nooyi"])
            "primary_query": "",  # AI fills: tight photo search query fallback (e.g. "SEBI building Mumbai")
            "treatment": "auto",  # leave "auto" (direct embed) unless a clean single subject
                                  # (product on plain bg, well-lit portrait) clearly warrants "cutout"
            "slides": [],         # CAROUSEL ONLY, AI fills: one {"image_url": "", "entities": [], "primary_query": ""}
                                  # per entry in copy.carousel_slides.slides, same length, same order.
            "rules": [
                "RELEVANCE IS EVERYTHING - the image must be 100% about THIS story.",
                "PREFERRED: if you can search/browse the web, find the real photo directly (like a person",
                "googling the story) and put its URL in image_url - this skips the fallback waterfall entirely.",
                "Fallback waterfall (used only if image_url is blank): article og:image -> Wikipedia lead",
                "image for entities -> Brave image search on entities[0]/primary_query -> branded fallback.",
                "So if you can't pick directly, still give a SPECIFIC entity or a tight primary_query - not a generic one.",
                "Real photos only - no stock/generic filler.",
                "No foreign branding: never pick an image carrying another publication's/company's logo or watermark.",
                "The renderer auto-fits the photo (subject-aware cover crop, or letterbox for off-ratio images),",
                "so any real photo will sit cleanly. Only request 'cutout' for a clean single subject.",
                "CAROUSEL POSTS ONLY: also fill assets.slides with one entry per carousel slide (same order/length as",
                "copy.carousel_slides.slides) - each slide should get its OWN relevant image/entity/query, not a copy",
                "of image_url. Only repeat an image across slides if the source genuinely offers just one visual for",
                "multiple slides about that same single fact - never as a default."
            ]
        },

        "metadata": {
            "generated_at": "",
            "status": "pending_ai_fill"
        }
    }


def main():
    settings, brand, root = load_config()
    data_dir = root / settings["output"]["data_dir"]

    filtered_path = data_dir / "filtered_news.json"
    if not filtered_path.exists():
        print("filtered_news.json not found. Run filter_news.py first.")
        return

    with open(filtered_path) as f:
        filtered = json.load(f)

    briefs = []
    for article in filtered["articles"]:
        brief = generate_copy_brief(article, brand)
        briefs.append(brief)
        print(f"Brief created: {article['title'][:60]}...")

    output = {
        "generated_at": datetime.now().isoformat(),
        "count": len(briefs),
        "brand_voice": {
            "tone": "Confident, opinionated, conversational - like a smart friend sharing news",
            "audience": "Indian millennials/Gen-Z interested in startups, business, AI, tech",
            "language": "English with occasional Hindi words if natural (not forced)",
            "perspective": "News + opinion - we don't just report, we add our take"
        },
        "grounding_rules": [
            "Every headline, subline, caption, and carousel slide must be grounded in source_title, "
            "source_description, or source_text.",
            "Reframing, condensing, and adding your own opinionated take are all fine and encouraged.",
            "Inventing facts, numbers, dates, quotes, or names that aren't in the source is NOT allowed.",
            "If the source doesn't give you enough to write confidently, say less rather than making something up.",
        ],
        "briefs": briefs,
    }

    output_path = data_dir / "copy.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nGenerated {len(briefs)} copy briefs -> {output_path}")
    print("Next: AI agent fills the 'copy' text fields (grounded in source_text) and 'assets' hints in each brief.")
    print("Every static post uses one clean editorial template - no archetype to pick.")
    print("The single lever for quality is a RELEVANT photo: search the web directly if you can, or give a specific entity/primary_query.")


if __name__ == "__main__":
    main()
