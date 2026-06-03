# Daily Football News Brief

Twice-daily automated pipeline that pulls **2026 FIFA World Cup news** from
**Google News RSS**, uses the **Gemini API** to score each story for
newsworthiness and suitability for **Vietnamese readers**, writes **Vietnamese
summaries** for the best ones, and saves everything to a **CSV** (committed for
history) and a **Google Sheet**. Runs unattended on **GitHub Actions**.

## How it works

```
fetch (Google News RSS) → dedup → Gemini scores ALL ~50
   → rank by composite → Gemini briefs TOP 10 in Vietnamese
   → append to data/briefs.csv + Google Sheet
```

- **Source:** Google News public search RSS — free, no key, no quota.
- **Scope:** 2026 FIFA World Cup only; English sources, briefs translated to Vietnamese.
  Non-World-Cup articles are scored 0–2 and dropped (`RELEVANCE_MIN_COMPOSITE`).
- **Per run:** ~50 candidates fetched, all scored, off-topic dropped, top 10 briefed.
- **Schedule:** 06:00 & 19:00 Vietnam time (`23:00` & `12:00` UTC).
- **Gemini calls:** 2 per run (score batch + brief batch) on `gemini-2.5-flash`.

### Scoring
`composite = 0.6 * newsworthiness + 0.4 * reader_suitability` (each 0–10).
Tune the queries, weights, and counts in `src/config.py`.

### Output columns (CSV & Sheet)
`run_datetime_utc, run_slot, published, source, title_en, url,
newsworthiness, suitability, composite, rank, briefed, title_vi, brief_vi`

All ~50 scored rows are saved each run; `title_vi`/`brief_vi` are filled only
for the top 10.

## One-time setup

1. **Gemini API key** — create one at <https://aistudio.google.com/apikey>.
2. **Google Cloud service account**
   - Create a project, enable the **Google Sheets API** and **Google Drive API**.
   - Create a **service account**, add a **JSON key**, and download it.
3. **Google Sheet**
   - Create a sheet; copy its ID from the URL
     (`docs.google.com/spreadsheets/d/<ID>/edit`).
   - **Share the sheet with the service-account email** (the `client_email` in
     the JSON), with **Editor** access.

## Run locally

```bash
cd news-brief
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env       # fill in GEMINI_API_KEY, GOOGLE_SHEET_ID, creds path
# put the downloaded key at ./service-account.json (matches .env.example)

# Just inspect the fetched candidates (no Gemini, no writes):
python -m src.fetch_news

# CSV only, skip the Sheet:
python -m src.main --skip-sheet

# Full run (CSV + Google Sheet):
python -m src.main
```

## Deploy on GitHub Actions

1. Push this folder to a GitHub repo.
2. Add repository **secrets** (Settings → Secrets and variables → Actions):
   - `GEMINI_API_KEY`
   - `GOOGLE_SHEET_ID`
   - `GCP_SERVICE_ACCOUNT_JSON` — paste the **full contents** of the JSON key.
3. The workflow `.github/workflows/daily-brief.yml` runs on the two crons and on
   manual **workflow_dispatch**. It commits the updated `data/briefs.csv` back to
   the repo (needs `contents: write`, already configured).

> GitHub cron can be delayed a few minutes under load — fine for a news brief.

## Project layout

```
src/config.py       queries, weights, model, env loading
src/fetch_news.py   Google News RSS fetch + normalize + cross-run dedup
src/gemini_eval.py  score-all (1 call) + brief-top-N (1 call), Vietnamese
src/sinks.py        CSV append + Google Sheet append (gspread)
src/main.py         orchestrator
data/briefs.csv     durable history + dedup source (created on first run)
.github/workflows/daily-brief.yml   2 crons + dispatch + commit-back
```
