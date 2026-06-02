"""Crawl-Adapter: advertools im Subprozess (Reactor-Isolation), erfuellt ``CrawlPort``.

Der eigentliche Crawl laeuft in ``_worker`` (eigener Prozess); dieser Adapter startet
ihn, liest die erzeugte JSONL-Datei und parst sie ueber ``_parse`` (kein advertools-
Import hier, kein Reactor im Hauptprozess).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from geo_audit_loop.adapters.crawl._parse import parse_jsonl, rows_to_inventory
from geo_audit_loop.domain.errors import CrawlError
from geo_audit_loop.domain.inventory import CrawlOptions, PageInventory

_WORKER_MODULE = "geo_audit_loop.adapters.crawl._worker"
_DEFAULT_TIMEOUT_S = 300.0


class AdvertoolsCrawlAdapter:
    """Startet den advertools-Subprozess und liefert das geparste Seiten-Inventar."""

    def __init__(
        self,
        *,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        python_executable: str | None = None,
    ) -> None:
        self._timeout_s = timeout_s
        self._python = python_executable or sys.executable

    def crawl(self, domain: str, options: CrawlOptions) -> list[PageInventory]:
        """Crawlt ``domain`` via advertools-Subprozess und parst das Ergebnis."""
        with tempfile.TemporaryDirectory(prefix="geo-crawl-") as tmp:
            out_file = Path(tmp) / "crawl.jl"
            config = {
                "domain": domain,
                "out_file": str(out_file),
                "max_pages": options.max_pages,
                "download_delay_s": options.download_delay_s,
                "concurrent_per_domain": options.concurrent_per_domain,
                "respect_robots": options.respect_robots,
                "user_agent": options.user_agent,
            }
            self._run_worker(json.dumps(config))
            if not out_file.exists():
                return []
            rows = parse_jsonl(out_file.read_text(encoding="utf-8"))
            return rows_to_inventory(rows)

    def _run_worker(self, raw_config: str) -> None:
        try:
            proc = subprocess.run(
                [self._python, "-m", _WORKER_MODULE, raw_config],
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CrawlError(f"Crawl-Timeout nach {self._timeout_s}s") from exc
        if proc.returncode != 0:
            tail = (proc.stderr or "")[-500:]
            raise CrawlError(f"Crawl-Subprozess fehlgeschlagen (rc={proc.returncode}): {tail}")
