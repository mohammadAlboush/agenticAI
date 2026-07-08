"""CLI-Einstieg: einen Audit-Run starten und die Reports als rich-Terminal-UI ausgeben.

Beispiele:
    python -m geo_audit_loop --domain it-sicherheit.de            # Offline-Demo (Mock)
    python -m geo_audit_loop --domain it-sicherheit.de --explain  # + Sprint-2-Lern-Loop
    python -m geo_audit_loop --domain it-sicherheit.de --live     # Perplexity live
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from datetime import UTC, datetime

from rich.console import Console

from geo_audit_loop.cli.render import (
    render_coverage,
    render_deploy,
    render_effect,
    render_error,
    render_findings,
    render_fixplan,
    render_header,
    render_hitl,
    render_patterns,
    render_share_of_voice,
    render_summary,
    render_topflop,
)
from geo_audit_loop.config.settings import Settings
from geo_audit_loop.domain.errors import BudgetExceeded, GeoAuditError
from geo_audit_loop.domain.fingerprint import report_fingerprint
from geo_audit_loop.observability.logging import configure_logging
from geo_audit_loop.prompts.loader import load_probe_set


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Liest die CLI-Argumente."""
    parser = argparse.ArgumentParser(prog="geo_audit_loop", description="GEO-Audit-Run")
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
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Sprint-3-Fix-/Deploy-Loop: Patches ableiten, Freigabe (HITL), Dry-Run-Deploy "
        "(impliziert --explain)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Deploy-Schritt aktivieren (Alias zu --fix; reiner Dry-Run, kein externer Write)",
    )
    parser.add_argument(
        "--learn",
        action="store_true",
        help="Sprint-4-Lern-Loop: Gedaechtnis-Abruf vor dem Fix + Effekt-Re-Probe danach "
        "(schliesst den Regelkreis; impliziert --fix)",
    )
    parser.add_argument(
        "--approve-all",
        action="store_true",
        help="Alle Patches automatisch freigeben (nicht-interaktive Demo); sonst wird gefragt",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging-Level")
    parser.add_argument(
        "--live-crawl",
        action="store_true",
        help="Zieldomain real crawlen (advertools, langsam); Default: schnelles Sample-Inventar",
    )
    parser.add_argument(
        "--pace",
        type=float,
        default=0.0,
        help="Sekunden Pause zwischen den Report-Abschnitten (Demo/Praesentation)",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Run-Monitor (Web-Oberflaeche, read-only) statt eines Audit-Laufs starten",
    )
    parser.add_argument(
        "--port", type=int, default=8042, help="Port des Run-Monitors (nur mit --serve)"
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Vorgegebene run_id (Dashboard-Start; Default: zufaellige ID)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Fuehrt einen Run aus und rendert die Reports. Liefert den Exit-Code."""
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

    if args.serve:
        # Deferred Imports: uvicorn/starlette nur laden, wenn der Monitor gebraucht wird.
        import uvicorn

        from geo_audit_loop.webapp.app import create_app

        console = Console()
        console.print(
            f"[bold]Run-Monitor[/] auf [bold green]http://127.0.0.1:{args.port}[/]"
            f"  ·  DB: {settings.db_path}  ·  Beenden: Strg+C"
        )
        uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, log_level="warning")
        return 0

    version, prompts = load_probe_set(settings.prompt_set_version)
    run_id = args.run_id if args.run_id else uuid.uuid4().hex[:12]
    learn = args.learn
    fix = args.fix or args.apply or learn
    explain = args.explain or fix
    stage_label = (
        "Sprint 4 — Learning Loop"
        if learn
        else "Sprint 3 — Fix & Deploy"
        if fix
        else "Sprint 2 — Learning"
        if explain
        else "Sprint 1 — Foundation"
    )

    # Header sofort rendern — die schweren (deferred) CrewAI-Imports kommen erst danach,
    # damit die CLI nicht sekundenlang stumm bleibt.
    console = Console()
    render_header(
        console,
        domain=args.domain,
        run_id=run_id,
        seed=settings.run_seed,
        offline=not args.live,
        prompt_version=version,
        top_n=settings.top_n,
        stage_label=stage_label,
    )

    # Deferred Imports: erst nach dem Setzen der Telemetrie-Env (crewai wird dort geladen).
    from geo_audit_loop.cli.approval import InteractiveApproveGate
    from geo_audit_loop.cli.progress import (
        FlowProgressListener,
        build_progress,
        silence_crewai_console,
    )
    from geo_audit_loop.orchestration.approval import ApprovalGate
    from geo_audit_loop.orchestration.factory import assemble_run
    from geo_audit_loop.orchestration.sprint2_flow import Sprint2Pipeline
    from geo_audit_loop.orchestration.sprint3_flow import Sprint3Pipeline
    from geo_audit_loop.orchestration.sprint4_flow import Sprint4Pipeline

    # HITL-Gate: interaktiv (Default) oder Auto (--approve-all). Nur relevant bei --fix.
    gate: ApprovalGate | None = (
        InteractiveApproveGate(console) if (fix and not args.approve_all) else None
    )

    # Vor assemble_run: dort wird der Flow konstruiert und das erste CrewAI-Panel gefeuert.
    silence_crewai_console()
    assembly = assemble_run(
        settings,
        domain=args.domain,
        offline=not args.live,
        run_id=run_id,
        now=datetime.now(UTC),
        prompts=prompts,
        prompt_version=version,
        explain=explain,
        fix=fix,
        learn=learn,
        approval_gate=gate,
        live_crawl=args.live_crawl,
    )

    progress = build_progress(console)
    _listener = FlowProgressListener(
        progress=progress, pipeline=assembly.pipeline, cost_tracker=assembly.cost_tracker
    )
    started = time.monotonic()
    try:
        with progress:
            assembly.flow.kickoff()
    except BudgetExceeded as exc:
        render_error(console, title="Run abgebrochen (Budget)", message=str(exc))
        return 2
    except GeoAuditError as exc:
        render_error(console, title="Run fehlgeschlagen", message=str(exc))
        return 1
    finally:
        assembly.storage.close()
    duration = time.monotonic() - started

    def _pace() -> None:
        """Lesepause zwischen den Report-Abschnitten (nur mit --pace > 0)."""
        if args.pace > 0:
            time.sleep(args.pace)

    report = assembly.pipeline.report
    coverage = assembly.pipeline.coverage
    patterns = None
    audit = None
    fix_plan = None
    effect = None
    share = assembly.storage.load_sov_report(assembly.run_context.run_id)
    if report is not None:
        _pace()
        render_topflop(console, report)
        if share is not None:
            _pace()
            render_share_of_voice(console, share)
        if coverage is not None:
            _pace()
            render_coverage(console, coverage)
    if isinstance(assembly.pipeline, Sprint2Pipeline | Sprint3Pipeline | Sprint4Pipeline):
        patterns = assembly.pipeline.pattern_report
        audit = assembly.pipeline.audit_report
        if patterns is not None:
            _pace()
            render_patterns(console, patterns)
        if audit is not None:
            _pace()
            render_findings(console, audit)
    if isinstance(assembly.pipeline, Sprint3Pipeline | Sprint4Pipeline):
        fix_plan = assembly.pipeline.fix_plan
        decisions = assembly.pipeline.decisions
        deploy = assembly.pipeline.deploy_result
        if fix_plan is not None:
            _pace()
            render_fixplan(console, fix_plan)
        if fix_plan is not None and decisions is not None:
            _pace()
            render_hitl(console, fix_plan, decisions)
        if deploy is not None:
            _pace()
            render_deploy(console, deploy)
    if isinstance(assembly.pipeline, Sprint4Pipeline):
        effect = assembly.pipeline.effect_report
        if effect is not None:
            _pace()
            render_effect(console, effect)
    if report is not None:
        _pace()
        render_summary(
            console,
            snapshot=assembly.cost_tracker.snapshot(),
            fingerprint=report_fingerprint(
                report, patterns, audit, fix_plan, effect, coverage, share=share
            ),
            seed=settings.run_seed,
            duration_s=duration,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
