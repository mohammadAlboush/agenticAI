"""Gedaechtnis-Adapter: deterministisches, SQLite-gestuetztes Mock (Default, offline/CI).

Erfuellt ``MemoryPort`` (``store``/``retrieve``) ohne schwere Abhaengigkeit und ist
**voll deterministisch** — die Grundlage der bit-reproduzierbaren Offline-Lernschleife
(Projektregeln §7). Das Gedaechtnis liegt in einer **eigenen** Tabelle ``effect_hypotheses``
derselben SQLite-Datei (entkoppelt vom ``StoragePort``, CLAUDE.md §3.4: ``memory/`` haelt
die Persistenz hinter dem Port). Der Abruf ist strukturiert (Domain-/Hebel-Filter) und
deterministisch geordnet — kein Embedding, kein Zufall.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import cast

from geo_audit_loop.domain.effect import EffectHypothesis
from geo_audit_loop.domain.errors import StorageError
from geo_audit_loop.domain.memory import MemoryQuery

_SCHEMA = """
CREATE TABLE IF NOT EXISTS effect_hypotheses (
    hypothesis_id TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL,
    target_domain TEXT NOT NULL,
    target_url    TEXT NOT NULL,
    lever         TEXT NOT NULL,
    pyramid_level TEXT NOT NULL,
    change_type   TEXT NOT NULL,
    delta         REAL NOT NULL,
    confidence    REAL NOT NULL,
    observed_at   TEXT NOT NULL,
    payload       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_effect_hypotheses_domain_lever
    ON effect_hypotheses (target_domain, lever);
"""


class MockMemoryAdapter:
    """Deterministisches SQLite-Gedaechtnis (erfuellt ``MemoryPort``); kein Netz, kein RNG."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self.initialize()

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
        """Legt die ``effect_hypotheses``-Tabelle an, falls noch nicht vorhanden (idempotent)."""
        conn = self._connection()
        try:
            with self._lock:
                conn.executescript(_SCHEMA)
                conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"Memory-Schema fehlgeschlagen: {exc}") from exc

    def close(self) -> None:
        """Schliesst die Verbindung (im Test/CLI nach dem Run)."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def store(self, hypothesis: EffectHypothesis) -> None:
        """Persistiert eine Hypothese idempotent (Upsert ueber ``hypothesis_id``)."""
        conn = self._connection()
        try:
            with self._lock:
                conn.execute(
                    "INSERT OR REPLACE INTO effect_hypotheses "
                    "(hypothesis_id, run_id, target_domain, target_url, lever, pyramid_level, "
                    "change_type, delta, confidence, observed_at, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        hypothesis.hypothesis_id,
                        hypothesis.run_id,
                        hypothesis.target_domain,
                        hypothesis.target_url,
                        hypothesis.lever.value,
                        hypothesis.pyramid_level.value,
                        hypothesis.change_type.value,
                        hypothesis.delta,
                        hypothesis.confidence,
                        hypothesis.observed_at.isoformat(),
                        hypothesis.model_dump_json(),
                    ),
                )
                conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"Hypothese speichern fehlgeschlagen: {exc}") from exc

    def retrieve(self, context: MemoryQuery) -> list[EffectHypothesis]:
        """Liefert domaingefilterte Hypothesen, deterministisch geordnet, begrenzt auf ``top_k``.

        Pflicht-Filter ``target_domain`` (Isolationsgrenze). Optionale Gleichheits-Filter
        (Hebel/Pyramide/Aenderungsart/URL). Reihenfolge: hoechste Confidence, dann groesstes
        ``|delta|``, dann neueste Beobachtung, dann ``hypothesis_id`` — voll deterministisch.
        """
        clauses = ["target_domain = ?"]
        params: list[object] = [context.target_domain]
        if context.lever is not None:
            clauses.append("lever = ?")
            params.append(context.lever.value)
        if context.pyramid_level is not None:
            clauses.append("pyramid_level = ?")
            params.append(context.pyramid_level.value)
        if context.change_type is not None:
            clauses.append("change_type = ?")
            params.append(context.change_type.value)
        if context.target_url is not None:
            clauses.append("target_url = ?")
            params.append(context.target_url)
        params.append(context.top_k)
        sql = (
            "SELECT payload FROM effect_hypotheses WHERE "
            + " AND ".join(clauses)
            + " ORDER BY confidence DESC, ABS(delta) DESC, observed_at DESC, hypothesis_id ASC "
            "LIMIT ?"
        )
        conn = self._connection()
        try:
            with self._lock:
                rows = cast("list[sqlite3.Row]", conn.execute(sql, tuple(params)).fetchall())
        except sqlite3.Error as exc:
            raise StorageError(f"Hypothesen laden fehlgeschlagen: {exc}") from exc
        return [EffectHypothesis.model_validate_json(row["payload"]) for row in rows]
