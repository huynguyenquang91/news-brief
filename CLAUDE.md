# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run pipeline (CSV only, no Sheet)
python -m src.main --skip-sheet

# Full run (CSV + Google Sheet)
python -m src.main

# Inspect RSS candidates without Gemini or writes
python -m src.fetch_news
```

The venv must be built against the Framework Python (`/Library/Frameworks/Python.framework/Versions/3.14/bin/python3`), not Homebrew, to avoid a broken SSL symlink.

## Architecture

Single pipeline: **fetch → score → filter → brief → write**

```
src/config.py       All tuning knobs: queries, tier tables, weights, env vars
src/fetch_news.py   Google News RSS fetch, normalize, cross-run dedup via CSV
src/filters.py      Tier-based filter scoring (source / article type / keyword)
src/gemini_eval.py  Gemini calls: score all (~50) + brief top N in Vietnamese
src/sinks.py        CSV append + Google Sheet append (gspread)
src/main.py         Orchestrator (5 steps, printed progress)
data/briefs.csv     Durable history; also the dedup source for future runs
```

### Data flow

1. `fetch_articles()` — polls 10 Google News RSS queries, deduplicates against recent rows in `data/briefs.csv` (lookback window = `DEDUP_LOOKBACK_DAYS`), returns up to `FETCH_LIMIT` articles sorted newest-first.
2. `score_articles()` — one Gemini call scores all articles on `newsworthiness` + `reader_suitability` (0–10) and classifies `article_type`. Returns `ScoredArticle` objects with `composite` and `combined_score`.
3. Filter step in `main.py` — drops articles below `RELEVANCE_MIN_COMPOSITE` (off-topic non-WC items scored 0–2 by prompt design).
4. `brief_top()` — one Gemini call writes Vietnamese `title_vi` + `brief_vi` for the top `BRIEF_TOP_N` articles.
5. `write_csv()` + `append_google_sheet()` — appends all scored rows (not just top N) to persistent storage.

### Scoring & ranking

`composite = 0.6 × newsworthiness + 0.4 × reader_suitability`

`filter_priority = 0.3 × (1/source_tier) + 0.3 × (1/type_tier) + 0.4 × (1/keyword_tier)` — each dimension uses tier tables in `config.py` (T1=highest). Unmatched = 0.

`combined_score = 0.7 × (composite/10) + 0.3 × filter_priority` — used for final ranking.

### Tier tables (edit in `config.py` only)

| Dimension | T1 | T2 | T3 |
|---|---|---|---|
| Source | BBC, Guardian, Reuters, AP | Sky Sports, ESPN, Athletic | Marca, L'Equipe, Bild |
| Article type | breaking_news, transfer_news | match_report, interview, analysis | preview, roundup, feature |
| Keyword | Messi, Ronaldo, Man Utd, World Cup draw/final | Mbappé, Haaland, Brazil, France, Vietnam | Deschamps, fixture, AFC, tickets |

### CSV columns

`run_datetime_utc, run_slot, published, source, title_en, url, newsworthiness, suitability, composite, article_type, source_tier, type_tier, keyword_tier, top_keywords, filter_priority, combined_score, rank, briefed, title_vi, brief_vi`

`COLUMNS` in `config.py` is the single source of truth for column order in both CSV and Sheet.

## Environment variables

| Variable | Required | Notes |
|---|---|---|
| `GEMINI_API_KEY` | Yes | From Google AI Studio |
| `GOOGLE_SHEET_ID` | Yes (Sheet runs) | Long ID from Sheet URL |
| `GOOGLE_APPLICATION_CREDENTIALS` | Local | Path to service-account JSON file |
| `GCP_SERVICE_ACCOUNT_JSON` | CI | Full JSON contents (used in GitHub Actions) |
| `GEMINI_MODEL` | No | Default: `gemini-2.5-flash` |

## GitHub Actions

Workflow at `.github/workflows/daily-brief.yml` runs at `23:00 UTC` (06:00 VN) and `12:00 UTC` (19:00 VN), plus manual `workflow_dispatch`. After each run it commits the updated `data/briefs.csv` back to the repo (needs `contents: write` permission, already set). Requires three repo secrets: `GEMINI_API_KEY`, `GOOGLE_SHEET_ID`, `GCP_SERVICE_ACCOUNT_JSON`.
