#!/bin/bash
cd /Users/mohanvamshi/job-hunter
export PYTHONPATH=/Users/mohanvamshi/job-hunter
exec /Users/mohanvamshi/job-hunter/.venv/bin/uvicorn chat.app:app --host 0.0.0.0 --port 8080
