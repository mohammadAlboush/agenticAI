"""ASGI-Einstieg fuer Container-/Produktionsbetrieb (uvicorn/gunicorn).

Der CLI-Modus ``--serve`` bindet bewusst nur an ``127.0.0.1`` (lokale Steuerzentrale,
Sicherheitsdefault). Fuer den Betrieb hinter einem externen ASGI-Server im Container
exponiert dieses Modul die Starlette-App als Modul-Attribut ``app``. Host und Port
bestimmt dann der Server (siehe ``Dockerfile``-CMD: ``0.0.0.0:$PORT``), nicht die App.

Konfiguration ausschliesslich ueber Umgebungsvariablen (``pydantic-settings``):
z. B. ``GEO_DB_PATH`` fuer die SQLite. Ohne API-Keys laeuft das Dashboard vollstaendig
offline und deterministisch (Mock-Engines, Seed 42) — ideal fuer eine oeffentliche Demo.
"""

from __future__ import annotations

from geo_audit_loop.webapp.app import create_app

# Modul-weites ASGI-Objekt fuer ``uvicorn geo_audit_loop.webapp.asgi:app``.
app = create_app()
