# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: Build React frontend
# ─────────────────────────────────────────────────────────────────────────────
FROM node:26-alpine AS frontend-builder

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --frozen-lockfile 2>/dev/null || npm install

COPY frontend/ .
RUN npx vite build --outDir /frontend-dist --emptyOutDir


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: Python backend + bundled frontend
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.14-slim

WORKDIR /app

# Install Python dependencies. gcc is only needed to build any wheels at pip time;
# install it, build, then purge it in the SAME layer so it never ships in the image.
#
# apt-get upgrade: the python:3.11-slim tag usually trails the Debian archive by a
# point release, so the base layer ships packages with published fixes already
# available. Without this the image scan fails on base-image findings that nothing
# in this project causes and nothing in this project can otherwise fix.
#
# setuptools: the stock base image bundles setuptools 79.0.1, which vendors
# jaraco.context 5.3.0 and wheel 0.45.1 under setuptools/_vendor/. Both carry HIGH
# advisories. The code is never imported by this application, but the scanner reads
# the vendored metadata and blocks on it regardless. setuptools 81.0.0 dropped the
# vendored jaraco.context and moved to wheel 0.46.3; pinned exact for reproducible
# builds, so bump deliberately rather than letting it float.
COPY backend/requirements.txt .
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends gcc \
    && pip install --no-cache-dir --upgrade "setuptools==84.0.0" \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy backend source
COPY backend/app ./app

# Copy built frontend into static serving directory
COPY --from=frontend-builder /frontend-dist ./app/static

# Create a non-root user and the data mount points it must read/write.
# /data (SQLite DB) must be writable; /financial-data is read-only-mounted at runtime.
RUN mkdir -p /data /financial-data \
    && groupadd -r tally && useradd -r -g tally -d /app tally \
    && chown -R tally:tally /app /data /financial-data

USER tally

EXPOSE 8091

ENV DATABASE_URL="sqlite:////data/tally.db"
ENV FINANCIAL_DATA_PATH="/financial-data"
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8091"]
