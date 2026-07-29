# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
# geo-audit-loop — Container fuer die Web-Steuerzentrale (Dashboard).
#
# Startet dieselbe Starlette-App wie `python -m geo_audit_loop --serve`, aber an
# 0.0.0.0:$PORT (siehe webapp/asgi.py), damit sie hinter einem Reverse-Proxy /
# in einer Container-Plattform (Cloudflare Containers, Hugging Face Spaces, Render,
# Cloud Run …) erreichbar ist. Ein im Dashboard gestarteter Lauf laeuft — wie im
# Terminal — als Subprozess (`python -m geo_audit_loop …`); der ist im Container
# derselbe Interpreter (.venv) und funktioniert unveraendert.
#
# Ohne API-Keys laeuft alles offline & deterministisch (Mock-Engines, Seed 42).
# Fuer den Live-Modus: `.env` als Secrets/Umgebungsvariablen der Plattform setzen.
# Build:  docker build -t geo-audit-loop .
# Run:    docker run --rm -p 8080:8080 geo-audit-loop   →  http://localhost:8080
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Abhaengigkeiten reproduzierbar via uv aus dem Lock installieren ──
FROM python:3.12-slim AS builder

# uv (Astral) fuer den byte-reproduzierbaren, gepinnten Install aus uv.lock.
# Bewusst ``latest`` (statt Minor-Pin): Reproduzierbarkeit garantiert ohnehin ``uv.lock``
# via ``--frozen``; ``latest`` vermeidet Build-Bruch durch einen nicht existenten Tag.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Build-Tools nur in der Builder-Stage (falls ein Rad aus Quellen gebaut werden muss).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Erst nur die Manifeste kopieren → Layer-Cache bleibt bei reinen Code-Aenderungen warm.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

# Nur Laufzeit-Abhaengigkeiten (kein dev), gepinnt aus dem Lock, Paket nicht editierbar.
# Das schwere Extra `memory` (torch/chroma) bleibt bewusst aussen vor — der
# deterministische MockMemoryAdapter braucht es nie.
RUN uv sync --frozen --no-dev --no-editable

# ── Stage 2: schlanke Laufzeit ohne Build-Tools ──────────────────────────────
FROM python:3.12-slim AS runtime

# Laufzeit-Bibliotheken fuer lxml/advertools (die manylinux-Wheels linken libxml2/xslt).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libxml2 \
        libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Nicht als root laufen.
RUN useradd --create-home --uid 10001 app

# Die fertige venv aus der Builder-Stage uebernehmen (enthaelt das installierte Paket).
COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # SQLite in einen beschreibbaren Pfad (als Volume mountbar → Laeufe ueberleben Neustarts).
    GEO_DB_PATH=/data/geo.db \
    PORT=8080

# Beschreibbares Datenverzeichnis fuer die SQLite (dem app-User gehoerend).
# Kein Docker-``VOLUME``: Railway lehnt die Instruktion ab (nutzt eigene Volumes, die man
# bei Bedarf separat an /data mountet). Ohne Volume ist die SQLite ephemer — fuer die
# Offline-Demo (deterministisch, Seed 42) voellig ausreichend.
RUN mkdir -p /data && chown app:app /data

USER app
EXPOSE 8080

# Shell-Form, damit ${PORT} von der Plattform expandiert werden kann (CF/HF/Render setzen PORT).
# exec → uvicorn wird PID 1 und empfaengt SIGTERM sauber.
CMD exec uvicorn geo_audit_loop.webapp.asgi:app --host 0.0.0.0 --port ${PORT:-8080} --log-level warning
