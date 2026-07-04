#!/usr/bin/env python3
"""
MoatDaily - Robust Article Fetching
Wraps Scrapling's stealth Fetcher (bypasses 403/hotlink-protected sites that a
plain GET often can't reach) with a plain-urllib fallback, so the pipeline
never hard-depends on it. Used to pull an article's og:image and full body
text (source_text) so write_copy.py can ground its copy in the real story
instead of guessing from just the title/description.

If Scrapling (or its browser/TLS deps, the `scrapling[fetchers]` extra) isn't
installed, everything degrades to a plain urllib GET - slightly less robust
against anti-bot blocks, but the pipeline keeps working unattended either way.
"""

import re
import urllib.request

USER_AGENT = "Mozilla/5.0 (compatible; MoatDailyBot/1.0; +https://moatdaily.example)"
REQUEST_TIMEOUT = 12
MAX_TEXT_CHARS = 4000

_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _fallback_fetch(url):
    """Plain GET + regex og:image + crude tag-stripped body text."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            if resp.status != 200:
                return {"og_image": None, "text": ""}
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return {"og_image": None, "text": ""}

    match = _OG_IMAGE_RE.search(html)
    og_image = match.group(1).strip() if match else None
    text = _TAG_RE.sub(" ", html)
    text = re.sub(r"\s+", " ", text).strip()[:MAX_TEXT_CHARS]
    return {"og_image": og_image, "text": text}


def fetch_article(url):
    """
    Returns {"og_image": str|None, "text": str} for the article at `url`.
    Tries Scrapling's stealth fetcher first (handles 403/hotlink-protected
    sites); falls back to a plain GET if Scrapling isn't installed or fails.
    """
    if not url:
        return {"og_image": None, "text": ""}

    try:
        from scrapling.fetchers import Fetcher
        page = Fetcher.get(url, timeout=REQUEST_TIMEOUT)
        if page.status == 200:
            og = page.css('meta[property="og:image"]::attr(content)')
            paragraphs = page.css("p::text")
            text = " ".join(str(p) for p in paragraphs).strip()[:MAX_TEXT_CHARS]
            og_image = str(og[0]) if og else None
            if og_image or text:
                return {"og_image": og_image, "text": text}
    except Exception:
        pass  # Scrapling unavailable or blocked - fall through to plain fetch

    return _fallback_fetch(url)
