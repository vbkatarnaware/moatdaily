# Concerns & Technical Debt

## Network Dependencies & Fragility
- **Image Downloading (`render_post.py`)**: The script attempts to download images directly from the URLs provided in the RSS feeds. Many news sites block automated scraping (403 Forbidden) or have hotlink protection, resulting in failed downloads. The fallback is a gradient background, but this reduces visual quality.
- **Logo Fetching**: The pipeline relies on `logo.clearbit.com` (which is deprecated/shut down) and `logos.hunter.io`. These are undocumented or unsupported APIs. If they change, logo overlay will fail silently.

## AI Reliability
- **Copy Generation**: The pipeline assumes the AI Agent will correctly parse the `write-copy` skill and properly fill the empty `text` fields inside the `copy.json` structure without breaking the JSON schema.
- **Visual Review Gate**: The `review-post` skill asks the AI to visually inspect generated images. CLI agents (like Claude Code or Antigravity) currently have limited multimodal capabilities, making the subjective checks ("image_not_blurry", "overall_premium_feel") unreliable or impossible for the agent to execute autonomously.

## State Management
- **Stateless Runs**: `raw_news.json` and `filtered_news.json` are overwritten entirely on each run. There is no historical state to prevent fetching/posting the exact same news story on consecutive days if it remains in the RSS feed.

## Missing Features
- **Auto-Publishing**: The pipeline generates images and copy but does not currently post them to Instagram. A human must manually upload the output.
