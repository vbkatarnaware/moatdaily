"""
Test harness for the single-template renderer.
Builds data/copy.json from scratch with a spread of cases (portrait -> cover crop,
landscape -> letterbox, cutout opt-in, sourcing-fails -> branded fallback, + a 4:5
carousel) so `render_html.py` can be run end-to-end without an LLM in the loop.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from write_copy import generate_copy_brief, load_config  # noqa: E402

ARTICLES = [
    {
        "id": "test_founder_01",
        "title": "Nithin Kamath shares the one investing strategy for long-term wealth",
        "description": "Zerodha's founder on protecting long-term wealth.",
        "url": "https://en.wikipedia.org/wiki/Nithin_Kamath",
        "suggested_post_type": "static",
    },
    {
        "id": "test_quote_01",
        "title": "Indra Nooyi on why she could only become CEO in America",
        "description": "Ex-PepsiCo CEO Indra Nooyi reflects on meritocracy.",
        "url": "https://en.wikipedia.org/wiki/Indra_Nooyi",
        "suggested_post_type": "static",
    },
    {
        "id": "test_landscape_01",
        "title": "Mumbai overtakes Beijing as Asia's billionaire capital",
        "description": "India's financial hub now has more billionaires than any Asian city.",
        "url": "https://en.wikipedia.org/wiki/Mumbai",
        "suggested_post_type": "static",
    },
    {
        "id": "test_cutout_01",
        "title": "This is the smartphone Lenovo built just for kids",
        "description": "No games, no browser, no social media.",
        "url": "https://en.wikipedia.org/wiki/Smartphone",
        "suggested_post_type": "static",
    },
    {
        "id": "test_fallback_01",
        "title": "SEBI tightens F&O rules to curb retail losses",
        "description": "New position limits aim to protect small traders.",
        "url": "https://example.com/nonexistent-article-xyz",
        "suggested_post_type": "static",
    },
    {
        "id": "test_carousel_01",
        "title": "Moneyview secures SEBI nod for a 1,500 Cr IPO",
        "description": "Another Indian fintech unicorn hits the public markets.",
        "url": "https://en.wikipedia.org/wiki/Initial_public_offering",
        "suggested_post_type": "carousel",
    },
]


def main():
    settings, brand, root = load_config()
    briefs = [generate_copy_brief(a, brand) for a in ARTICLES]

    disclaimer = "\n\n📸 Images used for editorial/educational purposes."

    # 1. Founder portrait -> near-portrait Wikipedia image -> cover crop
    b = briefs[0]
    b["copy"]["kicker"]["text"] = "MARKETS"
    b["copy"]["headline"]["text"] = "Nithin Kamath's one rule for **long-term wealth**"
    b["copy"]["subline"]["text"] = (
        "The Zerodha founder says surviving market cycles beats timing them - "
        "the investors who stay in are the ones who compound."
    )
    b["copy"]["caption"]["text"] = (
        "Timing the market or time in the market?\n\n"
        "Nithin Kamath says the founders and investors who actually build wealth are the "
        "ones who stay invested through every crash, not the ones chasing the perfect entry.\n\n"
        "Compounding rewards patience, not precision.\n\n"
        "Do you time the market or trust the process?\n\n"
        "---\n#NithinKamath #Zerodha #WealthBuilding #IndianStockMarket #Investing #PersonalFinance #StartupIndia #MarketWisdom"
        f"{disclaimer}"
    )
    b["assets"]["entities"] = ["Nithin Kamath"]

    # 2. Quote / portrait -> cover crop, no kicker
    b = briefs[1]
    b["copy"]["headline"]["text"] = "“I could only have become CEO **in America**”"
    b["copy"]["subline"]["text"] = (
        "Ex-PepsiCo chief Indra Nooyi on how the US system rewarded an outsider - "
        "a chance she says she'd never have gotten back home."
    )
    b["copy"]["caption"]["text"] = (
        "Would Indra Nooyi have become CEO if she'd stayed in India?\n\n"
        "Her answer: probably not. She credits America's meritocratic system for giving an "
        "outsider the shot that a more rigid hierarchy back home wouldn't have.\n\n"
        "It's a blunt take on how opportunity gets distributed, and it still stings.\n\n"
        "Do you agree, or is this an outdated read on India's system?\n\n"
        "---\n#IndraNooyi #PepsiCo #WomenInLeadership #CEO #IndianDiaspora #Leadership #CareerGrowth #GlassCeiling"
        f"{disclaimer}"
    )
    b["assets"]["entities"] = ["Indra Nooyi"]

    # 3. Landscape source (city skyline) -> should LETTERBOX, not crop to death
    b = briefs[2]
    b["copy"]["kicker"]["text"] = "WEALTH"
    b["copy"]["headline"]["text"] = "Mumbai is now Asia's **billionaire capital**"
    b["copy"]["subline"]["text"] = (
        "The city overtook Beijing this year, adding more ten-figure fortunes than "
        "any other Asian metro as Indian markets surged."
    )
    b["copy"]["caption"]["text"] = (
        "Mumbai just quietly overtook Beijing.\n\n"
        "More billionaires now call India's financial capital home than any other city in "
        "Asia, on the back of a surging stock market and a wave of new-economy IPOs.\n\n"
        "Wealth creation in India is compounding faster than most people realize.\n\n"
        "Does this change how you see India's growth story?\n\n"
        "---\n#Mumbai #Billionaires #IndianEconomy #WealthCreation #StockMarket #IndiaGrowth #Sensex #Nifty"
        f"{disclaimer}"
    )
    b["assets"]["entities"] = ["Mumbai"]
    b["assets"]["primary_query"] = "Mumbai city skyline"

    # 4. Cutout opt-in (clean single subject)
    b = briefs[3]
    b["copy"]["kicker"]["text"] = "PRODUCT"
    b["copy"]["headline"]["text"] = "Lenovo built a **smartphone for kids**"
    b["copy"]["subline"]["text"] = (
        "No games, no browser, no social feeds - just calls, texts and a locked-down "
        "launcher parents control from their own phone."
    )
    b["copy"]["caption"]["text"] = (
        "What if a kid's first phone couldn't distract them at all?\n\n"
        "Lenovo's new phone strips out games, browsers and social media entirely - just "
        "calling, texting, and a launcher parents lock down remotely.\n\n"
        "It's a quiet bet that less is the actual selling point here.\n\n"
        "Would you hand this to your kid instead of a regular smartphone?\n\n"
        "---\n#Lenovo #ParentingTech #KidsSmartphone #DigitalWellbeing #TechForFamilies #GadgetLaunch #ScreenTime #ParentingIndia"
        f"{disclaimer}"
    )
    b["assets"]["primary_query"] = "smartphone on plain background"
    b["assets"]["treatment"] = "cutout"

    # 5. Sourcing all fails -> branded gradient fallback (never a broken image)
    b = briefs[4]
    b["copy"]["kicker"]["text"] = "MARKETS"
    b["copy"]["headline"]["text"] = "SEBI tightens the screws on **F&O trading**"
    b["copy"]["subline"]["text"] = (
        "New position limits and margin rules aim to slow the retail derivatives frenzy "
        "that wiped out a majority of small traders last year."
    )
    b["copy"]["caption"]["text"] = (
        "SEBI just made it harder to gamble your savings away on F&O.\n\n"
        "New position limits and margin rules are aimed squarely at the retail derivatives "
        "frenzy that wiped out a majority of small traders last year.\n\n"
        "Protection or overreach? Depends who you ask.\n\n"
        "Will this actually stop retail traders from chasing options?\n\n"
        "---\n#SEBI #StockMarket #FnO #RetailTraders #IndianMarkets #Regulation #Trading #PersonalFinance"
        f"{disclaimer}"
    )
    b["assets"]["entities"] = ["ZzzNonexistentEntity9000"]

    # 6. Carousel (4:5)
    b = briefs[5]
    b["copy"]["caption"]["text"] = (
        "Moneyview just joined the IPO queue.\n\n"
        "The fintech secured SEBI's nod for a 1,500 Cr IPO after turning profitable in FY24, "
        "riding the same wave of Indian startups heading public this year.\n\n"
        "Profitability before filing is still rare enough to be notable.\n\n"
        "Would you buy into this IPO?\n\n"
        "---\n#Moneyview #IPO #SEBI #IndianFintech #Startups #IPOAlert #FintechIndia #StockMarket"
        f"{disclaimer}"
    )
    b["copy"]["carousel_slides"]["slides"] = [
        {"text": "Moneyview just secured SEBI's nod for a **1,500 Cr IPO**"},
        {"text": "The fintech turned **profitable** in FY24 before filing."},
        {"text": "It joins a wave of Indian startups **going public**."},
        {"text": "The listing will test public appetite for **fintech**."},
        {"text": "Would you buy in? **Tell us below.**"},
    ]

    output = {
        "generated_at": datetime.now().isoformat(),
        "count": len(briefs),
        "brand_voice": {},
        "briefs": briefs,
    }

    with open(root / "data" / "copy.json", "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"✅ Wrote {len(briefs)} test briefs → data/copy.json")


if __name__ == "__main__":
    main()
