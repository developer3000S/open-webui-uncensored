#!/usr/bin/env bash
# Local dev server. Settings come from the repo .env, which open_webui/env.py
# re-reads with override=True, so exporting them here would only be shadowed.
# For a dev-only CORS origin, put it in .env:
#   CORS_ALLOW_ORIGIN='http://localhost:5173;http://localhost:8080'
PORT="${PORT:-8080}"
uvicorn open_webui.main:app --port $PORT --host 0.0.0.0 --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" --reload
