---
name: filter-news
description: Score and filter news articles for India relevance, engagement potential, and uniqueness. Selects top 3-6 stories from raw_news.json. Outputs filtered_news.json.
version: 1.0.0
author: moatdaily
---

# Filter News

## Objective
From 30-50 raw articles, select the top 3-6 stories that will make the best Instagram posts for an Indian audience.

## When to Use
- After `fetch-news` has run and `data/raw_news.json` exists
- Second step of the MoatDaily pipeline

## Steps
1. Run the filter script:
   ```bash
   cd /Users/vipulkatarnaware/Documents/AI\ Agents/moatdaily
   python scripts/filter_news.py --count 4
   ```
   This also drops any article already recorded in `data/posted_history.json` (written by `log-post` after a prior day's run), so the same story isn't re-selected.
2. Review the scored output - the script shows scores for each selected article
3. **YOUR ROLE AS AI AGENT**: Read `data/filtered_news.json` and add your reasoning:
   - For each selected article, evaluate: Is this ACTUALLY interesting for Indian millennials/Gen-Z?
   - Would this spark debate or comments on Instagram?
   - Is this news that people would share with friends?
   - If any story is weak, swap it with a lower-ranked one from `data/raw_news.json`

## Scoring Logic
- **India Relevance (40%)**: Keywords, Indian sources, India-specific topics
- **Engagement (35%)**: Controversy, numbers, launches, opinions
- **Uniqueness (25%)**: Not too many similar stories

## Rules for Story Selection
- SKIP: Local US/EU news with no India impact
- KEEP: Global AI/tech news (everyone cares about OpenAI, Google, etc.)
- PRIORITIZE: Indian startups, funding rounds, IPOs, policy changes
- BONUS: Stories that can generate debate (opinions, controversial takes)

## Next Step
→ Run the `write-copy` skill
