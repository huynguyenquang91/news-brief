"""Central configuration for the daily football news brief pipeline.

Values are read from environment variables (loaded from a local ``.env`` when
present) so the same code runs locally and in GitHub Actions.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Paths -----------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CSV_PATH = DATA_DIR / "briefs.csv"

# --- Gemini ----------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# --- Google Sheet ----------------------------------------------------------
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
SHEET_WORKSHEET = os.getenv("SHEET_WORKSHEET", "briefs")
# Either a path to a JSON key file (local) or raw JSON contents (CI).
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
GCP_SERVICE_ACCOUNT_JSON = os.getenv("GCP_SERVICE_ACCOUNT_JSON", "")

# --- Pipeline tuning -------------------------------------------------------
FETCH_LIMIT = int(os.getenv("FETCH_LIMIT", "50"))   # candidate articles per run
BRIEF_TOP_N = int(os.getenv("BRIEF_TOP_N", "10"))   # how many get Vietnamese briefs
DEDUP_LOOKBACK_DAYS = int(os.getenv("DEDUP_LOOKBACK_DAYS", "3"))

# Drop anything Gemini scores below this composite (off-topic = not 2026 World Cup).
# Non-WC articles are scored 0-2 by the prompt, so 3.0 cleanly excludes them.
RELEVANCE_MIN_COMPOSITE = float(os.getenv("RELEVANCE_MIN_COMPOSITE", "3.0"))

# Composite score weighting (newsworthiness vs reader suitability).
WEIGHT_NEWSWORTHINESS = 0.6
WEIGHT_SUITABILITY = 0.4

# --- Filter framework: tier tables -----------------------------------------
# Tier 1 = highest priority. Unmatched = None (no boost).

SOURCE_TIERS: dict[int, list[str]] = {
    1: ["BBC", "The Guardian", "Guardian", "Reuters", "AP News", "Associated Press"],
    2: ["Sky Sports", "ESPN", "The Athletic", "Goal", "Football365"],
    3: ["Marca", "AS", "L'Equipe", "Bild", "Gazzetta", "Sport", "90min"],
}

# Article types emitted by Gemini (see _SCORE_SCHEMA in gemini_eval.py).
ARTICLE_TYPE_TIERS: dict[int, list[str]] = {
    1: ["breaking_news", "transfer_news"],
    2: ["match_report", "interview", "analysis"],
    3: ["preview", "roundup", "feature"],
}

# Keywords matched against title + snippet (case-insensitive, partial match).
KEYWORD_TIERS: dict[int, list[str]] = {
    1: ["Messi", "Ronaldo", "Man Utd", "Manchester United", "World Cup draw",
        "World Cup final", "World Cup winner"],
    2: ["Mbappé", "Mbappe", "Haaland", "Neymar", "Vinicius", "Bellingham",
        "Brazil", "France", "England", "Argentina", "Germany", "Spain",
        "Vietnam", "Việt Nam"],
    3: ["Deschamps", "fixture", "schedule", "group stage", "host city",
        "ticket", "qualification", "AFC", "CONCACAF"],
}

# Weights for each dimension (must sum to 1.0).
FILTER_WEIGHT_SOURCE  = 0.30
FILTER_WEIGHT_TYPE    = 0.30
FILTER_WEIGHT_KEYWORD = 0.40

# Weight blending Gemini composite (0–10) vs filter priority (0–1).
# combined_score = WEIGHT_GEMINI * (composite/10) + WEIGHT_FILTER * filter_priority
WEIGHT_GEMINI = 0.70
WEIGHT_FILTER = 0.30

# --- Google News RSS queries ----------------------------------------------
# 2026 FIFA World Cup (USA / Canada / Mexico), English-language sources.
# Results merged + deduped; briefs are translated to Vietnamese downstream.
NEWS_QUERIES = [
    "2026 FIFA World Cup",
    "World Cup 2026",
    "World Cup 2026 squad",
    "World Cup 2026 fixtures schedule",
    "World Cup 2026 groups",
    "World Cup 2026 host cities",
    "World Cup 2026 USA Canada Mexico",
    "World Cup 2026 tickets",
    "World Cup 2026 star players",
    "World Cup 2026 AFC Asia teams",
]

# Google News RSS locale: English/US gives broad international coverage.
NEWS_HL = os.getenv("NEWS_HL", "en-US")
NEWS_GL = os.getenv("NEWS_GL", "US")
NEWS_CEID = os.getenv("NEWS_CEID", "US:en")

# CSV / Sheet column order (single source of truth).
COLUMNS = [
    "run_datetime_utc",
    "run_slot",
    "published",
    "source",
    "title_en",
    "url",
    "newsworthiness",
    "suitability",
    "composite",
    "article_type",
    "source_tier",
    "type_tier",
    "keyword_tier",
    "top_keywords",
    "filter_priority",
    "combined_score",
    "rank",
    "briefed",
    "title_vi",
    "brief_vi",
]
