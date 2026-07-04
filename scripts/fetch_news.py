#!/usr/bin/env python3
"""
MoatDaily - News Fetcher
Discovery layers, in order: Google News search RSS (per-vertical queries -
Google's own India news ranking, closest to "a human googling every morning"),
publisher RSS feeds, and Currents API (optional, only if a key is configured).
Outputs: data/raw_news.json

Usage: python scripts/fetch_news.py
"""

import json
import hashlib
import urllib.parse
from datetime import datetime
from pathlib import Path

import requests
import feedparser
import yaml

import sanitize


def load_config():
    root = Path(__file__).parent.parent
    with open(root / "config" / "settings.yaml") as f:
        settings = yaml.safe_load(f)
    with open(root / "config" / "news_sources.yaml") as f:
        sources = yaml.safe_load(f)
    return settings, sources, root


def fetch_google_news_search(sources, max_per_query=8):
    """
    Google News search RSS, bucketed per vertical (startup/business/tech/ai) so
    all four get guaranteed coverage every run - free, no key. This is the
    "human googling India-relevant news" layer; India geo-targeted via hl/gl/ceid.
    """
    articles = []
    queries_by_vertical = sources.get("google_news_queries", {})

    for vertical, queries in queries_by_vertical.items():
        for query in queries:
            url = (
                "https://news.google.com/rss/search?q="
                + urllib.parse.quote(f"{query} when:1d")
                + "&hl=en-IN&gl=IN&ceid=IN:en"
            )
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:max_per_query]:
                    source_name = "Google News"
                    source_href = ""
                    if hasattr(entry, "source") and entry.source:
                        source_name = entry.source.get("title", source_name)
                        source_href = entry.source.get("href", "")

                    # Google News RSS 'summary' is just a raw '<a href=...>Title</a> Source'
                    # anchor back to the redirect page, not a real snippet - strip it to
                    # plain text. It's usually still thin (near-duplicate of the title);
                    # write_copy.py's source_text (scraped article body) is the real
                    # grounding source, this is only a secondary hint.
                    description = sanitize.strip_html(entry.get("summary", ""))[:500]

                    articles.append({
                        "id": hashlib.md5(entry.get("link", "").encode()).hexdigest()[:12],
                        "title": entry.get("title", "").strip(),
                        "description": description,
                        "source": source_name,
                        "source_domain": source_href,  # publisher homepage - not the article URL
                        "url": entry.get("link", ""),
                        "image_url": "",
                        "published_at": entry.get("published", ""),
                        "category": vertical,
                        "fetch_source": "google_news",
                        "search_query": query,
                    })
            except Exception as e:
                print(f"[WARN] Google News search failed for '{query}': {e}")

    return articles


def fetch_rss_feeds(sources):
    """Publisher RSS - trusted, curated sources across all four verticals."""
    articles = []
    all_feeds = []

    for group in ["india_startup", "global_tech", "business", "ai"]:
        for feed_config in sources["rss_feeds"].get(group, []):
            all_feeds.append((feed_config, group))

    for feed_config, group in all_feeds:
        try:
            feed = feedparser.parse(feed_config["url"])
            for entry in feed.entries[:10]:  # Max 10 per feed
                image_url = ""
                if hasattr(entry, "media_content") and entry.media_content:
                    image_url = entry.media_content[0].get("url", "")
                elif hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
                    image_url = entry.media_thumbnail[0].get("url", "")
                elif hasattr(entry, "enclosures") and entry.enclosures:
                    image_url = entry.enclosures[0].get("href", "")

                published = ""
                if hasattr(entry, "published"):
                    published = entry.published
                elif hasattr(entry, "updated"):
                    published = entry.updated

                articles.append({
                    "id": hashlib.md5(entry.get("link", "").encode()).hexdigest()[:12],
                    "title": entry.get("title", "").strip(),
                    "description": entry.get("summary", "").strip()[:500],
                    "source": feed_config["name"],
                    "url": entry.get("link", ""),
                    "image_url": image_url,
                    "published_at": published,
                    "category": group,
                    "fetch_source": "rss",
                    "source_weight": feed_config.get("weight", 5),
                })
        except Exception as e:
            print(f"[WARN] RSS feed failed: {feed_config['name']} - {e}")

    return articles


def fetch_currents_api(settings, sources):
    """Optional - Currents API, 1000 req/day, only runs if a key is configured."""
    api_key = settings["news"].get("currents_api_key")
    if not api_key:
        return []

    base_url = sources["api"]["currents"]["base_url"]
    articles = []

    for category in settings["news"]["categories"]:
        try:
            resp = requests.get(
                f"{base_url}/latest-news",
                params={
                    "apiKey": api_key,
                    "language": "en",
                    "category": category,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("news", []):
                    articles.append({
                        "id": hashlib.md5(item.get("url", "").encode()).hexdigest()[:12],
                        "title": item.get("title", "").strip(),
                        "description": item.get("description", "").strip(),
                        "source": item.get("author", "Unknown"),
                        "url": item.get("url", ""),
                        "image_url": item.get("image", ""),
                        "published_at": item.get("published", ""),
                        "category": category,
                        "fetch_source": "currents_api",
                    })
            else:
                print(f"[WARN] Currents API returned {resp.status_code} for {category}")
        except Exception as e:
            print(f"[ERROR] Currents API fetch failed for {category}: {e}")

    return articles


def deduplicate(articles):
    """Remove duplicate articles by URL hash."""
    seen = set()
    unique = []
    for a in articles:
        if a["id"] not in seen:
            seen.add(a["id"])
            unique.append(a)
    return unique


def main():
    settings, sources, root = load_config()
    data_dir = root / settings["output"]["data_dir"]
    data_dir.mkdir(parents=True, exist_ok=True)

    print("[1/3] Fetching from Google News search (startup/business/tech/ai)...")
    google_articles = fetch_google_news_search(sources)
    print(f"      -> {len(google_articles)} articles from Google News")

    print("[2/3] Fetching from publisher RSS feeds...")
    rss_articles = fetch_rss_feeds(sources)
    print(f"      -> {len(rss_articles)} articles from RSS")

    if settings["news"].get("currents_api_key"):
        print("[3/3] Fetching from Currents API (optional)...")
        api_articles = fetch_currents_api(settings, sources)
        print(f"      -> {len(api_articles)} articles from API")
    else:
        print("[3/3] Currents API key not configured - skipping (optional, not required)")
        api_articles = []

    print("Deduplicating...")
    all_articles = deduplicate(google_articles + rss_articles + api_articles)
    print(f"      -> {len(all_articles)} unique articles")

    output = {
        "fetched_at": datetime.now().isoformat(),
        "total_count": len(all_articles),
        "articles": all_articles,
    }

    output_path = data_dir / "raw_news.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(all_articles)} articles to {output_path}")
    return output_path


if __name__ == "__main__":
    main()
