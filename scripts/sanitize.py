#!/usr/bin/env python3
"""
MoatDaily - Text Sanitizer
Applied everywhere user-facing text is assembled (render, caption, sheet log)
so no em dash and no stray publication-name credit ever reaches an actual post,
regardless of what the copy-writing step produced.
"""

import html
import re

_EM_DASH_RE = re.compile(r"[–—]")  # en dash, em dash
_TAG_RE = re.compile(r"<[^>]+>")

_PUBLICATION_NAMES = [
    "ETtech", "Economic Times", "TechCrunch", "Bloomberg", "Reuters", "Mint",
    "LiveMint", "Moneycontrol", "Forbes India", "Inc42", "YourStory",
    "StartupTalky", "Indian Express", "The Verge", "Wired", "Ars Technica",
]

_PUBLICATION_RE = re.compile(
    r"\b(?:via|from|according to)?\s*\b(" + "|".join(re.escape(n) for n in _PUBLICATION_NAMES) + r")\b[:,]?\s*",
    re.IGNORECASE,
)

DISCLAIMER = "📸 Images used for editorial/educational purposes."


def clean_text(text):
    """Em/en dashes -> hyphens, strip publication-name credits, collapse whitespace."""
    if not text:
        return text
    text = _EM_DASH_RE.sub("-", text)
    text = _PUBLICATION_RE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_html(text):
    """
    Strip HTML tags and unescape entities. Google News RSS 'summary' fields for
    search-result entries are just a raw anchor tag back to the redirect page
    (e.g. '<a href="...">Title</a>&nbsp;&nbsp;<font>Source</font>') rather than a
    real snippet - this turns that into plain text (often still short/thin, but
    at least not garbage markup).
    """
    if not text:
        return text
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def title_key(title):
    """
    Normalized dedup key for a headline/title, used by posted_history.json.
    Google News RSS links are per-crawl proxy URLs that change daily even for
    the same underlying story, so a URL hash alone isn't a reliable "already
    posted this" check - matching on the normalized title text catches it too.
    """
    normalized = re.sub(r"[^a-z0-9]+", "", (title or "").lower())
    return normalized[:80]


def ensure_disclaimer(caption):
    """Code-enforced - the editorial/educational credit line can never be silently
    dropped by the copy-writing step, since it's added here regardless."""
    caption = clean_text(caption) or ""
    if "editorial" in caption.lower() or "educational" in caption.lower():
        return caption
    sep = "\n\n" if caption else ""
    return f"{caption}{sep}{DISCLAIMER}"
