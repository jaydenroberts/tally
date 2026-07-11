# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: Build React frontend
# ─────────────────────────────────────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --frozen-lockfile 2>/dev/null || npm install

COPY frontend/ .
RUN npx vite build --outDir /frontend-dist --emptyOutDir


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: Python backend + bundled frontend
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies. gcc is only needed to build any wheels at pip time;
# install it, build, then purge it in the SAME layer so it never ships in the image.
COPY backend/requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
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
