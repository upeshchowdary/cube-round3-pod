# Hosted demo image (Render): the built UI and the orchestrator API in one service. See docs/deploy-render.md.

# --- 1. build the UI
FROM node:22-slim AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
# Login (Supabase): Render passes the service's environment variables as build args. Vite bakes these two public
# values into the bundle; without them the login page offers only the demo profiles.
ARG VITE_SUPABASE_URL=""
ARG VITE_SUPABASE_ANON_KEY=""
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY
RUN npm run build

# --- 2. Python app
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LOG_LEVEL=WARNING
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=ui /ui/dist ui/dist
# The real product photos are not in git: download them (data/photos.json; each one checked against its sha256).
RUN python scripts/fetch_photos.py

# Run every case once at build time (replay mode, no keys needed), so the dashboard has data the moment the service
# starts. Overrides and new runs made on the site are kept until the next deploy or restart (Render's disk is not kept).
RUN python -m orchestration.run --all --fresh \
 && python -m orchestration.run --all --cases data/input/my_cases.json \
 && if [ -f data/input/UNIT-C26RM-001/pack/open_box.jpg ]; then \
      RETURNS_LIVE_FALLBACK=0 python -m orchestration.run --all --cases data/input/returns_photo_cases.json; fi

EXPOSE 8100
CMD ["sh", "-c", "exec uvicorn orchestration.web:app --host 0.0.0.0 --port ${PORT:-8100}"]
