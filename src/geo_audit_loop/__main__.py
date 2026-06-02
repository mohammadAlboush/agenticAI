"""CLI-Einstieg: einen Sprint-1-Run starten und den Top/Flop-Report ausgeben.

Beispiele:
    python -m geo_audit_loop --domain it-sicherheit.de            # Offline-Demo (Mock)
    python -m geo_audit_loop --domain it-sicherheit.de --live      # Perplexity live
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import UTC, datetime

from geo_audit_loop.config.settings import Settings
from geo_audit_loop.domain.errors import BudgetExceeded, GeoAuditError
from geo_audit_loop.domain.findings import TopFlopEntry, TopFlopReport
from geo_audit_loop.observability.logging import configure_logging
from geo_audit_loop.prompts.loader import load_probe_set


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Liest die CLI-Argumente."""
    parser = argparse.ArgumentParser(prog="geo_audit_loop", description="Sprint-1 GEO-Audit-Run")
    parser.add_argument("--domain", default="it-sicherheit.de", help="Zieldomain")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="Mock-Engines (Standard)")
    mode.add_argument("--live", action="store_true", help="Perplexity live (braucht Key + Proxies)")
    parser.add_argument("--top-n", type=int, default=None, help="Groesse der Top/Flop-Liste")
    parser.add_argument("--seed", type=int, default=None, help="Run-Seed (Reproduzierbarkeit)")
    parser.add_argument("--log-level", default="INFO", help="Logging-Level")
    return parser.parse_args(argv)


def _entry_line(entry: TopFlopEntry) -> str:
    """Formatiert eine Top/Flop-Zeile."""
    return (
        f"  {entry.position:>2}. {entry.citation_count:>3}x  "
        f"rate={entry.citation_rate:.2f}  {entry.url}"
    )


def _print_report(report: TopFlopReport) -> None:
    """Gibt den Top/Flop-Report menschenlesbar aus."""
    print(f"\n=== GEO-Sichtbarkeit: {report.target_domain} (run {report.run_id}) ===")
    print(f"Probes: {report.n_probes} | Seiten: {report.n_pages}\n")
    print("TOP (am haeufigsten zitiert):")
    for entry in report.top:
        print(_entry_line(entry))
    print("\nFLOP (selten/nie zitiert):")
    for entry in report.flop:
        print(_entry_line(entry))


def main(argv: list[str] | None = None) -> int:
    """Fuehrt einen Sprint-1-Run aus und gibt den Report aus. Liefert den Exit-Code."""
    os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")
    # CrewAI gibt Flow-Panels mit Emoji aus; auf der Windows-cp1252-Konsole sonst charmap-Fehler.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    args = _parse_args(argv)
    configure_logging(args.log_level)

    settings = Settings()
    updates: dict[str, object] = {}
    if args.top_n is not None:
        updates["top_n"] = args.top_n
    if args.seed is not None:
        updates["run_seed"] = args.seed
    if updates:
        settings = settings.model_copy(update=updates)

    version, prompts = load_probe_set(settings.prompt_set_version)
    # Deferred Import: erst nach dem Setzen der Telemetrie-Env (crewai wird dort geladen).
    from geo_audit_loop.orchestration.factory import assemble_run

    assembly = assemble_run(
        settings,
        domain=args.domain,
        offline=not args.live,
        run_id=uuid.uuid4().hex[:12],
        now=datetime.now(UTC),
        prompts=prompts,
        prompt_version=version,
    )
    try:
        assembly.flow.kickoff()
    except BudgetExceeded as exc:
        print(f"Run abgebrochen (Budget): {exc}")
        return 2
    except GeoAuditError as exc:
        print(f"Run fehlgeschlagen: {exc}")
        return 1
    finally:
        assembly.storage.close()

    if assembly.pipeline.report is not None:
        _print_report(assembly.pipeline.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
