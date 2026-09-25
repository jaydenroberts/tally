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
# apt-get upgrade: the python slim tags usually trail the Debian archive by a
# point release, so the base layer ships packages with published fixes already
# available. Without this the image scan fails on base-image findings that nothing
# in this project causes and nothing in this project can otherwise fix.
#
# Two packages are managed by hand in the layer below, both for the same reason:
# the image scanner reads vendored dependency metadata and blocks on it even
# though this application never imports the code.
#
# setuptools is pinned exact rather than left to float, so a bump is a
# deliberate, reviewable change. python:3.14-slim ships no setuptools at all,
# unlike 3.11-slim which bundled 79.0.1 with vulnerable copies of jaraco.context
# and wheel vendored underneath it, so this line now installs setuptools rather
# than upgrading it. 84.0.0 scans clean.
#
# pip is removed at the end of that layer. python:3.14-slim ships pip 26.2.1,
# which vendors msgpack 1.1.2 and setuptools 70.3.0 under pip/_vendor/. Both
# carry fixable HIGH advisories, GHSA-6v7p-g79w-8964 and CVE-2025-47273, and the
# scanner reports both as installed packages. Upgrading pip does not fix it:
# 26.2.1 is the latest release and still pins those two versions. Nothing in the
# running image needs pip once the dependencies are installed, so deleting it
# removes the finding by removing the code rather than by waiving it. Measured
# 2026-09-19 with trivy 0.70.0 at the gate's own settings: 2 fixable HIGH with
# pip present, 0 with it removed, and the backend suite is 203 passing either way.
#
# Two caveats. There is no pip inside the running container, so installing a
# package with docker exec will not work; add it to backend/requirements.txt and
# rebuild, which is the intended path regardless. And this removes pip from the
# import path, not from the image: python still ships ensurepip/_bundled/pip-*.whl,
# so python -m ensurepip restores pip and its vendored copies along with it. The
# scanner does not read inside wheels, which is why the gate is clean. Do not
# treat "no pip" as a hardened boundary.
COPY backend/requirements.txt .
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends gcc \
    && pip install --no-cache-dir --upgrade "setuptools==84.0.0" \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove gcc \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall -y pip

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

# No curl/wget in this image (slim base, pip removed above) — python's stdlib
# urllib needs no new package. start-period covers first-boot work (owner
# bootstrap, the v1.4.5 pre-migration snapshot-and-verify, the recurring-timer
# task startup) before failures start counting. interval/timeout/retries are
# sized for a small single-writer SQLite app: a 3s stall answering a
# no-auth, no-DB-write endpoint is already a real signal, and 3 consecutive
# misses (90s) avoids flapping on a momentary GC pause rather than papering
# over a genuine hang.
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8091/api/health', timeout=2)"

ENV DATABASE_URL="sqlite:////data/tally.db"
ENV FINANCIAL_DATA_PATH="/financial-data"
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8091"]
