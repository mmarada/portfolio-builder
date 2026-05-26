"""Vercel serverless entry point — mounts the FastAPI chat app."""
import sys
from pathlib import Path

# Make the project root importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from chat.app import app  # noqa: F401 — Vercel imports `app`
