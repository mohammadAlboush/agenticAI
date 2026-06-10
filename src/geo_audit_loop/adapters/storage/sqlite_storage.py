"""Storage-Adapter: SQLite-Persistenz fuer Runs, Probes, Seiten und Reports.

Implementiert ``StoragePort``. Idempotenz/Checkpointing ueber den Primaerschluessel
``(run_id, prompt_id, engine_id, proxy_label)`` der Probes-Tabelle (Projektregeln §6).
Komplexe Objekte liegen als Pydantic-JSON-Blob; nur die fuer Checkpoint/Abfrage
noetigen Schluesselspalten sind separat indiziert.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from geo_audit_loop.domain.audit import AuditReport
from geo_audit_loop.domain.errors import StorageError
from geo_audit_loop.domain.findings import TopFlopReport
from geo_audit_loop.domain.inventory import PageInventory
from geo_audit_loop.domain.probe import EngineId, ProbeResult
from geo_audit_loop.domain.run import RunRecord
from geo_audit_loop.domain.templates import PatternReport

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id  TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS probes (
    run_id      TEXT NOT NULL,
    prompt_id   TEXT NOT NULL,
    engine_id   TEXT NOT NULL,
    proxy_label TEXT NOT NULL,
    payload     TEXT NOT NULL,
    PRIMARY KEY (run_id, prompt_id, engine_id, proxy_label)
);
CREATE TABLE IF NOT EXISTS pages (
    run_id  TEXT NOT NULL,
    url     TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (run_id, url)
);
CREATE TABLE IF NOT EXISTS reports (
    run_id  TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS patterns (
    run_id  TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audits (
    run_id  TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reasoning_log (
    run_id         TEXT NOT NULL,
    task           TEXT NOT NULL,
    model          TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    raw_text       TEXT NOT NULL
);
"""


class SqliteStorage:
    """SQLite-Implementierung des ``StoragePort``."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        # CrewAI fuehrt Flow-Schritte ggf. in einem anderen Thread aus; der Zugriff ist
        # sequentiell. check_same_thread=False + Lock erlauben das sicher.
        self._lock = threading.Lock()

    # --- Verbindung / Lifecycle ---------------------------------------------
    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            try:
                self._db_path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
                conn.row_factory = sqlite3.Row
                self._conn = conn
            except sqlite3.Error as exc:
                raise StorageError(f"Konnte SQLite nicht oeffnen ({self._db_path}): {exc}") from exc
        return self._conn

    def initialize(self) -> None:
        """Legt das Schema an, falls noch nicht vorhanden (idempotent)."""
        conn = self._connection()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"Schema-Initialisierung fehlgeschlagen: {exc}") from exc

    def close(self) -> None:
        """Schliesst die Verbindung (im Test/CLI nach dem Run)."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # --- generische Helfer ---------------------------------------------------
    def _execute(self, sql: str, params: Sequence[object]) -> None:
        conn = self._connection()
        try:
            with self._lock:
                conn.execute(sql, tuple(params))
                conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"SQL fehlgeschlagen: {exc}") from exc

    def _fetchone(self, sql: str, params: Sequence[object]) -> sqlite3.Row | None:
        conn = self._connection()
        try:
            with self._lock:
                return cast("sqlite3.Row | None", conn.execute(sql, tuple(params)).fetchone())
        except sqlite3.Error as exc:
            raise StorageError(f"SQL fehlgeschlagen: {exc}") from exc

    def _fetchall(self, sql: str, params: Sequence[object]) -> list[sqlite3.Row]:
        conn = self._connection()
        try:
            with self._lock:
                return cast("list[sqlite3.Row]", conn.execute(sql, tuple(params)).fetchall())
        except sqlite3.Error as exc:
            raise StorageError(f"SQL fehlgeschlagen: {exc}") from exc

    # --- Runs ---------------------------------------------------------------
    def save_run(self, run: RunRecord) -> None:
        """Persistiert einen Run (Upsert ueber run_id)."""
        self._execute(
            "INSERT OR REPLACE INTO runs (run_id, payload) VALUES (?, ?)",
            (run.run_id, run.model_dump_json()),
        )

    def update_run(self, run: RunRecord) -> None:
        """Aktualisiert einen bestehenden Run (gleicher Upsert wie save_run)."""
        self.save_run(run)

    def load_run(self, run_id: str) -> RunRecord | None:
        """Laedt einen Run oder ``None``, falls unbekannt."""
        row = self._fetchone("SELECT payload FROM runs WHERE run_id = ?", (run_id,))
        return RunRecord.model_validate_json(row["payload"]) if row is not None else None

    # --- Probes -------------------------------------------------------------
    def save_probe(self, result: ProbeResult) -> None:
        """Persistiert eine Probe idempotent (UNIQUE run/prompt/engine/proxy)."""
        self._execute(
            "INSERT OR REPLACE INTO probes "
            "(run_id, prompt_id, engine_id, proxy_label, payload) VALUES (?, ?, ?, ?, ?)",
            (
                result.run_id,
                result.prompt_id,
                result.engine_id.value,
                result.proxy_label or "",
                result.model_dump_json(),
            ),
        )

    def has_probe(
        self, run_id: str, prompt_id: str, engine_id: EngineId, proxy_label: str | None
    ) -> bool:
        """Prueft, ob diese Probe-Zelle bereits erledigt ist (Checkpoint-Resume)."""
        row = self._fetchone(
            "SELECT 1 FROM probes "
            "WHERE run_id = ? AND prompt_id = ? AND engine_id = ? AND proxy_label = ?",
            (run_id, prompt_id, engine_id.value, proxy_label or ""),
        )
        return row is not None

    def load_probes(self, run_id: str) -> list[ProbeResult]:
        """Laedt alle Probes eines Runs (fuer Aggregation/Report)."""
        rows = self._fetchall(
            "SELECT payload FROM probes WHERE run_id = ? "
            "ORDER BY prompt_id, engine_id, proxy_label",
            (run_id,),
        )
        return [ProbeResult.model_validate_json(row["payload"]) for row in rows]

    # --- Pages --------------------------------------------------------------
    def save_pages(self, run_id: str, pages: list[PageInventory]) -> None:
        """Persistiert das gecrawlte Seiten-Inventar eines Runs."""
        conn = self._connection()
        try:
            with self._lock:
                conn.executemany(
                    "INSERT OR REPLACE INTO pages (run_id, url, payload) VALUES (?, ?, ?)",
                    [(run_id, page.page.url, page.model_dump_json()) for page in pages],
                )
                conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"Seiten speichern fehlgeschlagen: {exc}") from exc

    def load_pages(self, run_id: str) -> list[PageInventory]:
        """Laedt das Seiten-Inventar eines Runs."""
        rows = self._fetchall("SELECT payload FROM pages WHERE run_id = ? ORDER BY url", (run_id,))
        return [PageInventory.model_validate_json(row["payload"]) for row in rows]

    # --- Reports ------------------------------------------------------------
    def save_report(self, report: TopFlopReport) -> None:
        """Persistiert den Top/Flop-Report eines Runs."""
        self._execute(
            "INSERT OR REPLACE INTO reports (run_id, payload) VALUES (?, ?)",
            (report.run_id, report.model_dump_json()),
        )

    def load_report(self, run_id: str) -> TopFlopReport | None:
        """Laedt den Top/Flop-Report eines Runs oder ``None``."""
        row = self._fetchone("SELECT payload FROM reports WHERE run_id = ?", (run_id,))
        return TopFlopReport.model_validate_json(row["payload"]) if row is not None else None

    # --- Sprint-2-Lern-Artefakte -------------------------------------------
    def save_pattern_report(self, report: PatternReport) -> None:
        """Persistiert die geminten Templates eines Runs (Upsert ueber run_id)."""
        self._execute(
            "INSERT OR REPLACE INTO patterns (run_id, payload) VALUES (?, ?)",
            (report.run_id, report.model_dump_json()),
        )

    def load_pattern_report(self, run_id: str) -> PatternReport | None:
        """Laedt den PatternReport eines Runs oder ``None``."""
        row = self._fetchone("SELECT payload FROM patterns WHERE run_id = ?", (run_id,))
        return PatternReport.model_validate_json(row["payload"]) if row is not None else None

    def save_audit_report(self, report: AuditReport) -> None:
        """Persistiert die Audit-Findings eines Runs (Upsert ueber run_id)."""
        self._execute(
            "INSERT OR REPLACE INTO audits (run_id, payload) VALUES (?, ?)",
            (report.run_id, report.model_dump_json()),
        )

    def load_audit_report(self, run_id: str) -> AuditReport | None:
        """Laedt den AuditReport eines Runs oder ``None``."""
        row = self._fetchone("SELECT payload FROM audits WHERE run_id = ?", (run_id,))
        return AuditReport.model_validate_json(row["payload"]) if row is not None else None

    def append_reasoning_log(
        self, run_id: str, task: str, model: str, prompt_version: str, raw_text: str
    ) -> None:
        """Haengt die rohe LLM-Antwort eines Reasoning-Schritts an (Auditierbarkeit/Replay)."""
        self._execute(
            "INSERT INTO reasoning_log (run_id, task, model, prompt_version, raw_text) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, task, model, prompt_version, raw_text),
        )
