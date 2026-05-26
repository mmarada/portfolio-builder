import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

# Scraping
APIFY_TOKEN = os.getenv("APIFY_API_TOKEN", "")

# AI
HF_API_KEY = os.getenv("HUGGINGFACE_API_KEY", "")
HF_GENERATION_MODEL = "mistralai/Mistral-7B-Instruct-v0.2"
HF_SUMMARIZATION_MODEL = "facebook/bart-large-cnn"
HF_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Email
GMAIL_CREDENTIALS_FILE = BASE_DIR / os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json")
GMAIL_TOKEN_FILE = BASE_DIR / os.getenv("GMAIL_TOKEN_FILE", "token.json")
DIGEST_RECIPIENT = os.getenv("DIGEST_RECIPIENT", "")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# Job prefs
TARGET_ROLES = [r.strip() for r in os.getenv(
    "TARGET_ROLES",
    "PM,TPM,Product Manager,Technical Program Manager,Full Stack Engineer,Software Engineer"
).split(",")]

TARGET_LOCATIONS = [l.strip() for l in os.getenv(
    "TARGET_LOCATIONS",
    "San Francisco,New York,Remote,Austin,Seattle"
).split(",")]

MIN_MATCH_SCORE = float(os.getenv("MIN_JOB_MATCH_SCORE", "0.55"))

# Contact finder
HUNTER_API_KEY = os.getenv("HUNTER_API_KEY", "")

# Scheduler
DIGEST_SEND_TIME = os.getenv("DIGEST_SEND_TIME", "07:00")

# Paths
DB_PATH = BASE_DIR / "data" / "jobs.db"
RESUME_DIR = BASE_DIR / "resume"

# Deployment
# Set DATABASE_URL on Vercel to use PostgreSQL (same value as POSTGRES_SYNC_URL locally).
# Set POSTGRES_SYNC_URL locally so the scraper syncs SQLite → PG after each run.
POSTGRES_SYNC_URL = os.getenv("POSTGRES_SYNC_URL", "")
# Public URL of the deployed chat app — used in email digest links.
CHAT_BASE_URL = os.getenv("CHAT_BASE_URL", "http://localhost:8080")
