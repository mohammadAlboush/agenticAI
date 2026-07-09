"""Run-Verwaltung des Dashboards: Laeufe als Subprozess starten, stoppen, ueberwachen.

Ein Lauf wird als eigener Prozess gestartet (``python -m geo_audit_loop …``) — exakt
derselbe Code-Pfad wie im Terminal; das Dashboard beobachtet den Fortschritt wie bisher
ueber die SQLite. Die run_id wird VOR dem Start vergeben (``--run-id``), damit das
Dashboard den Lauf sofort zuordnen kann. ``stop()`` beendet den Prozess hart (Windows)
und markiert den Run als ABORTED — dank Idempotenz/Checkpointing kann derselbe Lauf
spaeter per CLI mit gleicher run_id fortgesetzt werden.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from geo_audit_loop.domain.run import RunStatus
from geo_audit_loop.ports.storage import StoragePort


class ProcessHandle(Protocol):
    """Minimaler Prozess-Griff (erfuellt von ``subprocess.Popen``; in Tests gefaked)."""

    def poll(self) -> int | None:
        """``None`` solange der Prozess laeuft, sonst Exit-Code."""
        ...

    def terminate(self) -> None:
        """Beendet den Prozess."""
        ...


SpawnFn = Callable[[list[str], dict[str, str]], ProcessHandle]


@dataclass(frozen=True)
class RunParams:
    """Formular-Parameter eines Dashboard-Starts."""

    domain: str
    offline: bool = True
    explain: bool = True
    fix: bool = False  # Sprint 3: Fix-/Deploy-Loop (Dashboard gibt automatisch frei)
    learn: bool = False  # Sprint 4: geschlossener Lern-Loop (Re-Probe + Gedaechtnis)
    top_n: int = 3
    seed: int = 42
    n_proxy_ips: int = 5
    live_engines: tuple[str, ...] = ()
    reasoning_provider: str = "mock"


def _default_spawn(args: list[str], env_overlay: dict[str, str]) -> ProcessHandle:
    """Startet den CLI-Lauf als losgeloesten Subprozess (kein neues Konsolenfenster)."""
    env = {**os.environ, **env_overlay}
    # mypy narrowt sys.platform nur im if-Statement, nicht im Ternary (CI laeuft auf Linux).
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(
        args,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


@dataclass
class RunManager:
    """Haelt die vom Dashboard gestarteten Prozesse (run_id -> Handle)."""

    storage: StoragePort
    spawn: SpawnFn | None = None
    _procs: dict[str, ProcessHandle] = field(default_factory=dict)

    def start(self, params: RunParams) -> str:
        """Startet einen Lauf als Subprozess und liefert die vorab vergebene run_id."""
        run_id = uuid.uuid4().hex[:12]
        args = [
            sys.executable,
            "-m",
            "geo_audit_loop",
            "--domain",
            params.domain,
            "--offline" if params.offline else "--live",
            "--top-n",
            str(params.top_n),
            "--seed",
            str(params.seed),
            "--run-id",
            run_id,
            "--log-level",
            "WARNING",
        ]
        if params.explain:
            args.append("--explain")
        if params.learn:
            # Sprint 4: schliesst den Loop (impliziert --fix); Dashboard gibt automatisch frei.
            args += ["--learn", "--approve-all"]
        elif params.fix:
            # Dashboard-Lauf gibt automatisch frei (nicht-interaktiv); Deploy bleibt Dry-Run.
            args += ["--fix", "--approve-all"]
        env_overlay = {
            "GEO_N_PROXY_IPS": str(params.n_proxy_ips),
            "GEO_REASONING_PROVIDER": params.reasoning_provider,
            "GEO_LIVE_ENGINES": ",".join(params.live_engines),
        }
        spawn = self.spawn if self.spawn is not None else _default_spawn
        self._procs[run_id] = spawn(args, env_overlay)
        return run_id

    def is_alive(self, run_id: str) -> bool:
        """True, solange der vom Dashboard gestartete Prozess dieses Laufs lebt."""
        proc = self._procs.get(run_id)
        return proc is not None and proc.poll() is None

    def stop(self, run_id: str) -> bool:
        """Beendet den Lauf-Prozess (falls aktiv) und markiert den Run als ABORTED."""
        proc = self._procs.pop(run_id, None)
        stopped = False
        if proc is not None and proc.poll() is None:
            proc.terminate()
            stopped = True
        # Status ERST nach terminate() lesen: ein gekillter Prozess schreibt nicht mehr.
        # Der Guard ueberschreibt einen bereits final geschriebenen Run (COMPLETED/FAILED)
        # nicht — so geht kein echtes Ergebnis durch das Stoppen verloren.
        record = self.storage.load_run(run_id)
        if record is not None and record.status in (RunStatus.RUNNING, RunStatus.PENDING):
            self.storage.update_run(
                record.model_copy(
                    update={
                        "status": RunStatus.ABORTED,
                        "finished_at": datetime.now(UTC),
                        "error": "vom Dashboard gestoppt",
                    }
                )
            )
            stopped = True
        return stopped
