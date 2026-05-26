# Job Hunter — Setup Guide

## 1. Install dependencies

```bash
cd ~/job-hunter
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## 2. Configure .env

```bash
cp .env.example .env
```

Edit `.env` and fill in:

| Key | Where to get it |
|-----|----------------|
| `APIFY_API_TOKEN` | [apify.com](https://console.apify.com/account/integrations) → API tokens |
| `HUGGINGFACE_API_KEY` | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |
| `DIGEST_RECIPIENT` | Your email address |
| `SMTP_USER` / `SMTP_PASSWORD` | Gmail App Password (Google Account → Security → App Passwords) |
| `TARGET_ROLES` | Comma-separated roles (default: PM, TPM, Full Stack Engineer) |
| `TARGET_LOCATIONS` | Comma-separated (default: SF, NYC, Remote, Austin, Seattle) |

## 3. Gmail OAuth (for Gmail drafts + sending)

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable **Gmail API**
3. Create OAuth 2.0 credentials (Desktop app) → Download `credentials.json`
4. Place `credentials.json` in the `~/job-hunter/` directory
5. Run once to complete OAuth:

```bash
python email_service/gmail_sender.py --auth
```

A browser window will open. Approve access. `token.json` is saved automatically.

## 4. Upload your resume

```bash
cp ~/Downloads/your-resume.pdf ~/job-hunter/resume/
```

Or upload via the chat UI at `http://localhost:8080`.

## 5. Run

### One-time full run (scrape → email)
```bash
python main.py
```

### Daily scheduler (runs at 7:00 AM by default)
```bash
python scheduler.py
```

### Chat UI only
```bash
python main.py --chat
# Open http://localhost:8080
```

### Resend digest from today's already-scraped jobs
```bash
python main.py --email
```

---

## Architecture

```
Apify actors                Playwright
(LinkedIn, Indeed,     +    (Fortune 500, YC,
 Jobright)                   VC startups)
         │                        │
         └──────────┬─────────────┘
                    ▼
             Job deduplication
             + HuggingFace scoring
             (sentence similarity vs resume)
                    │
         ┌──────────┼──────────────┐
         ▼          ▼              ▼
   SQLite DB   Contact finder  Email drafter
               (LinkedIn        (HuggingFace
                people search    Mistral-7B)
                + Hunter.io)
                    │
                    ▼
            Gmail API digest
            + Gmail drafts
            + SMTP fallback
                    │
                    ▼
         FastAPI chat UI (port 8080)
         - Job summaries
         - Gap analysis
         - Multi-turn Q&A
```

## Notes

- **LinkedIn scraping** uses Apify's residential proxies. LinkedIn ToS prohibits scraping — use at your own risk. The system still works without it (Indeed + career pages cover most roles).
- **HuggingFace free tier** has rate limits. If you hit them, add a small `time.sleep(1)` between batch calls in `ai/hf_client.py`.
- **Apify credits**: LinkedIn and Indeed scrapers consume Apify compute units. Monitor usage at [console.apify.com](https://console.apify.com).
- Jobs are deduplicated by URL. Re-running the same day only adds new postings.
