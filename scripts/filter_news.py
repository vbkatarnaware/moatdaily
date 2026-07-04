#!/usr/bin/env python3
"""
MoatDaily - News Filter & Scorer
Reads raw_news.json → scores on India relevance + engagement potential → outputs filtered_news.json

This script does RULE-BASED scoring. The AI agent adds reasoning on top.
Usage: python scripts/filter_news.py [--count 4]
"""

import json
import re
import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import yaml

import sanitize

# A handful of non-RFC-2822 formats seen across RSS/Currents feeds, tried after
# the standard email-date parser fails.
FALLBACK_DATE_FORMATS = [
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S %z",
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
]


def parse_published_at(raw):
    """Best-effort parse of a published_at string into a tz-aware UTC datetime.
    Returns None if it can't be parsed - caller treats that as "can't verify
    freshness" and drops the article rather than risking a stale post."""
    if not raw or not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw:
        return None

    try:
        dt = parsedate_to_datetime(raw)
        if dt is not None:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass

    for fmt in FALLBACK_DATE_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


def is_recent(article, max_age_hours, now=None):
    """True only if published_at parses AND falls within the cutoff.
    An unparseable/missing date is NOT treated as recent - we can't verify
    freshness, so we don't risk posting stale content."""
    now = now or datetime.now(timezone.utc)
    published = parse_published_at(article.get("published_at"))
    if published is None:
        return False
    age_hours = (now - published).total_seconds() / 3600
    return age_hours <= max_age_hours


def load_config():
    root = Path(__file__).parent.parent
    with open(root / "config" / "settings.yaml") as f:
        settings = yaml.safe_load(f)
    with open(root / "config" / "news_sources.yaml") as f:
        sources = yaml.safe_load(f)
    return settings, sources, root


def load_posted_history(data_dir):
    """Returns (id_set, title_key_set) of stories already posted on prior days,
    so the same story isn't re-selected on consecutive runs."""
    history_path = data_dir / "posted_history.json"
    if not history_path.exists():
        return set(), set()
    with open(history_path) as f:
        history = json.load(f)
    ids = {e["id"] for e in history.get("entries", [])}
    title_keys = {e["title_key"] for e in history.get("entries", [])}
    return ids, title_keys


def already_posted(article, posted_ids, posted_title_keys):
    return article["id"] in posted_ids or sanitize.title_key(article["title"]) in posted_title_keys


def score_india_relevance(article, signals):
    """Score 0-10 for India relevance."""
    score = 0
    text = f"{article['title']} {article['description']}".lower()

    # High-relevance India keywords
    for kw in signals["india_keywords"]["high"]:
        if kw.lower() in text:
            score += 3

    # Medium-relevance keywords
    for kw in signals["india_keywords"]["medium"]:
        if kw.lower() in text:
            score += 1

    # Source bonus: Indian sources get a boost
    india_sources = ["Economic Times", "Inc42", "YourStory", "StartupTalky",
                     "Indian Express", "Moneycontrol", "LiveMint", "Forbes India"]
    for src in india_sources:
        if src.lower() in article.get("source", "").lower():
            score += 2
            break

    # Skip signals - reduce score for irrelevant content
    for kw in signals["skip_keywords"]:
        if kw.lower() in text:
            score -= 5

    # Global tech news that EVERYONE cares about (AI, big tech) gets a pass
    global_pass = ["openai", "google", "apple", "microsoft", "meta", "nvidia",
                   "tesla", "sam altman", "elon musk", "ai ", "artificial intelligence",
                   "chatgpt", "gemini", "claude", "billion", "ipo"]
    for kw in global_pass:
        if kw.lower() in text:
            score += 1

    return min(max(score, 0), 10)


def score_engagement(article, signals):
    """Score 0-10 for engagement/viral potential."""
    score = 0
    text = f"{article['title']} {article['description']}".lower()

    for kw in signals["engagement_signals"]["high"]:
        if kw.lower() in text:
            score += 2

    for kw in signals["engagement_signals"]["medium"]:
        if kw.lower() in text:
            score += 1

    # Controversy / opinion bait detection
    opinion_triggers = ["controversial", "banned", "fired", "shocked", "exposed",
                        "truth about", "nobody talks about", "why", "how",
                        "breaking", "exclusive", "just announced", "war"]
    for kw in opinion_triggers:
        if kw in text:
            score += 1

    # Numbers in headline = more engaging
    if re.search(r'\$[\d.]+[BMK]|\d+%|₹[\d,]+', article["title"]):
        score += 2

    # Short punchy titles score higher
    word_count = len(article["title"].split())
    if word_count <= 12:
        score += 1

    return min(max(score, 0), 10)


def score_uniqueness(article, all_articles):
    """Score 0-10 - penalize if many similar articles exist."""
    title_words = set(article["title"].lower().split())
    similar_count = 0

    for other in all_articles:
        if other["id"] == article["id"]:
            continue
        other_words = set(other["title"].lower().split())
        overlap = len(title_words & other_words) / max(len(title_words), 1)
        if overlap > 0.5:
            similar_count += 1

    if similar_count == 0:
        return 10
    elif similar_count <= 2:
        return 7
    elif similar_count <= 5:
        return 4
    return 2


def filter_and_rank(articles, signals, count):
    """Score all articles, rank, return top N."""
    scored = []

    for article in articles:
        india_score = score_india_relevance(article, signals)
        engage_score = score_engagement(article, signals)
        unique_score = score_uniqueness(article, articles)

        # Weighted total: India relevance matters most
        total = (india_score * 0.4) + (engage_score * 0.35) + (unique_score * 0.25)

        article["scores"] = {
            "india_relevance": india_score,
            "engagement": engage_score,
            "uniqueness": unique_score,
            "total": round(total, 2),
        }
        scored.append(article)

    # Sort by total score descending
    scored.sort(key=lambda x: x["scores"]["total"], reverse=True)

    # Filter out very low scores
    filtered = [a for a in scored if a["scores"]["total"] >= 2.0]

    return filtered[:count]


def suggest_post_type(article):
    """Suggest static vs carousel based on content."""
    desc_len = len(article.get("description", ""))
    title_len = len(article.get("title", ""))

    if desc_len > 300 or "how" in article["title"].lower() or "why" in article["title"].lower():
        return "carousel"
    return "static"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=4, help="Number of posts to select")
    args = parser.parse_args()

    settings, sources, root = load_config()
    data_dir = root / settings["output"]["data_dir"]

    raw_path = data_dir / "raw_news.json"
    if not raw_path.exists():
        print("❌ raw_news.json not found. Run fetch_news.py first.")
        return

    with open(raw_path) as f:
        raw = json.load(f)

    articles = raw["articles"]
    signals = sources["relevance_signals"]

    posted_ids, posted_title_keys = load_posted_history(data_dir)
    before = len(articles)
    articles = [a for a in articles if not already_posted(a, posted_ids, posted_title_keys)]
    skipped = before - len(articles)
    if skipped:
        print(f"[0/3] Skipped {skipped} already-posted stor{'y' if skipped == 1 else 'ies'} (posted_history.json)")

    max_age_hours = settings["news"].get("max_age_hours", 24)
    now = datetime.now(timezone.utc)
    before = len(articles)
    stale = [a for a in articles if not is_recent(a, max_age_hours, now)]
    articles = [a for a in articles if is_recent(a, max_age_hours, now)]
    if stale:
        print(f"[0/3] Dropped {len(stale)} stale/undated stor{'y' if len(stale) == 1 else 'ies'} (older than {max_age_hours}h or no parseable date):")
        for a in stale[:10]:
            print(f"       - [{a.get('published_at') or 'no date'}] {a['title'][:70]}")
        if len(stale) > 10:
            print(f"       ...and {len(stale) - 10} more")

    print(f"[1/3] Scoring {len(articles)} articles...")
    top_articles = filter_and_rank(articles, signals, args.count)

    # Add post type suggestion
    for a in top_articles:
        a["suggested_post_type"] = suggest_post_type(a)

    print(f"[2/3] Selected top {len(top_articles)} stories")
    for i, a in enumerate(top_articles):
        print(f"  {i+1}. [{a['scores']['total']}] {a['title'][:80]}")
        print(f"     India:{a['scores']['india_relevance']} Engage:{a['scores']['engagement']} Unique:{a['scores']['uniqueness']} → {a['suggested_post_type']}")

    output = {
        "filtered_at": datetime.now().isoformat(),
        "selected_count": len(top_articles),
        "articles": top_articles,
    }

    output_path = data_dir / "filtered_news.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Saved {len(top_articles)} filtered articles to {output_path}")


if __name__ == "__main__":
    main()
