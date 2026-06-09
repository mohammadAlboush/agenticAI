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
from geo_audit_loop.domain.audit import AuditReport
from geo_audit_loop.domain.errors import BudgetExceeded, GeoAuditError
from geo_audit_loop.domain.findings import TopFlopEntry, TopFlopReport
from geo_audit_loop.domain.geo import LEVER_LABELS, PYRAMID_LABELS
from geo_audit_loop.domain.templates import PatternReport
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
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Sprint-2-Lern-Loop: Muster (warum) + priorisierte Findings (was tun) ausgeben",
    )
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


def _print_patterns(report: PatternReport) -> None:
    """Gibt die geminten Best-Practice-Templates aus (Sprint-2: 'warum ranken die Top-Seiten')."""
    print(f"\n=== WARUM ranken die Top-Seiten? {len(report.templates)} Muster (Pattern-Miner) ===")
    for tmpl in report.templates:
        levers = ", ".join(LEVER_LABELS[lever] for lever in tmpl.levers)
        print(f"\n  [{tmpl.template_id}] {tmpl.title}  (Konfidenz {tmpl.confidence:.2f})")
        print(f"      Ebene: {PYRAMID_LABELS[tmpl.pyramid_level]} | Hebel: {levers}")
        print(f"      {tmpl.summary}")


def _print_findings(report: AuditReport) -> None:
    """Gibt die priorisierten Audit-Findings aus (Sprint-2: 'was an den Flop-Seiten tun')."""
    print(f"\n=== WAS tun? {len(report.findings)} Findings (GEO-Auditor, priorisiert) ===")
    for position, finding in enumerate(report.findings, start=1):
        print(f"\n  {position}. [{finding.severity.value.upper()}] {finding.target_url}")
        print(
            f"      Ebene: {PYRAMID_LABELS[finding.pyramid_level]} | "
            f"Hebel: {LEVER_LABELS[finding.lever]}"
        )
        print(f"      Beleg: {finding.evidence}")
        print(f"      Fix:   {finding.recommendation}")


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
    from geo_audit_loop.orchestration.sprint2_flow import Sprint2Pipeline

    assembly = assemble_run(
        settings,
        domain=args.domain,
        offline=not args.live,
        run_id=uuid.uuid4().hex[:12],
        now=datetime.now(UTC),
        prompts=prompts,
        prompt_version=version,
        explain=args.explain,
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
    if isinstance(assembly.pipeline, Sprint2Pipeline):
        if assembly.pipeline.pattern_report is not None:
            _print_patterns(assembly.pipeline.pattern_report)
        if assembly.pipeline.audit_report is not None:
            _print_findings(assembly.pipeline.audit_report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
