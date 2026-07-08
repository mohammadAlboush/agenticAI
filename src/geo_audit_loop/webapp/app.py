"""Run-Steuerzentrale: Starlette-App ueber dem StoragePort (Praesentationsschicht).

Zeigt einen Lauf mit allen Schritten — Probe-Matrix (Engine x Prompt x Proxy),
Inventar, Top/Flop, Templates, Findings — und VERWALTET Laeufe: Starten (Subprozess
ueber den ``RunManager``, exakt der CLI-Code-Pfad), Stoppen, Verlauf, Loeschen.
Engine-/Reasoning-Live-Optionen erscheinen nur, wenn der jeweilige API-Key in der
``.env`` hinterlegt ist. Bindung ausschliesslich an 127.0.0.1.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from geo_audit_loop.adapters.storage.sqlite_storage import SqliteStorage
from geo_audit_loop.config.settings import Settings
from geo_audit_loop.domain.fingerprint import report_fingerprint
from geo_audit_loop.domain.probe import EngineId, ProbePhase, ProbeResult
from geo_audit_loop.domain.run import RunRecord, RunStatus
from geo_audit_loop.ports.storage import StoragePort
from geo_audit_loop.prompts.loader import load_probe_set
from geo_audit_loop.webapp.runner import RunManager, RunParams, SpawnFn

_STATIC_DIR = Path(__file__).parent / "static"
_ALLOWED_LIVE_ENGINES = frozenset({EngineId.PERPLEXITY.value, EngineId.GEMINI.value})
_ALLOWED_REASONING = frozenset({"mock", "saia", "claude"})
# Nur echte Hostnamen zulassen (keine Sonderzeichen -> kein Argument-Schmuggel/XSS-Vektor).
_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9-]{1,63})+$")


def _prompt_texts(version: str) -> dict[str, str]:
    """prompt_id -> Fragetext des versionierten Probe-Sets."""
    _, prompts = load_probe_set(version)
    return {prompt.prompt_id: prompt.text for prompt in prompts}


def _proxy_labels(probes: list[ProbeResult], fallback_n: int) -> list[str]:
    """Sortierte Proxy-Labels aus den Probes (vor dem ersten Ergebnis: Fallback-Slots)."""
    labels = sorted({probe.proxy_label or "" for probe in probes})
    if labels:
        return labels
    return [f"proxy-{i}" for i in range(fallback_n)]


def _selected_run(storage: StoragePort, request: Request) -> RunRecord | None:
    """Der per ``?run=`` gewaehlte Lauf, sonst der neueste."""
    run_id = request.query_params.get("run")
    if run_id:
        return storage.load_run(run_id)
    runs = storage.list_runs()
    return runs[0] if runs else None


def create_app(settings: Settings | None = None, *, spawn: SpawnFn | None = None) -> Starlette:
    """Baut die Steuerzentrale ueber der SQLite des Projekts.

    ``spawn`` ist nur fuer Tests gedacht (ersetzt den echten Subprozess-Start).
    """
    cfg = settings if settings is not None else Settings()
    storage = SqliteStorage(cfg.db_path)
    storage.initialize()  # idempotent; erlaubt Start vor dem ersten Lauf
    manager = RunManager(storage=storage, spawn=spawn)

    def index(request: Request) -> HTMLResponse:
        html = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    def config(request: Request) -> JSONResponse:
        engines = []
        if cfg.perplexity_api_key:
            engines.append("perplexity")
        if cfg.google_api_key:
            engines.append("gemini")
        reasoning = ["mock"]
        if cfg.saia_api_key:
            reasoning.append("saia")
        if cfg.anthropic_api_key:
            reasoning.append("claude")
        return JSONResponse(
            {
                "live_engines_available": engines,
                "reasoning_available": reasoning,
                "defaults": {
                    "domain": "it-sicherheit.de",
                    "top_n": cfg.top_n,
                    "seed": cfg.run_seed,
                    "n_proxy_ips": cfg.n_proxy_ips,
                },
            }
        )

    def runs_list(request: Request) -> JSONResponse:
        runs = [
            {
                **record.model_dump(mode="json"),
                "dashboard_alive": manager.is_alive(record.run_id),
            }
            for record in storage.list_runs()
        ]
        return JSONResponse({"runs": runs})

    async def runs_start(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except ValueError:
            return JSONResponse({"error": "Ungueltiger JSON-Body"}, status_code=400)
        domain = str(payload.get("domain", "")).strip().lower()
        if not domain or len(domain) > 253 or not _DOMAIN_RE.match(domain):
            return JSONResponse({"error": "Ungueltige Domain"}, status_code=400)
        offline = bool(payload.get("offline", True))
        live_engines = tuple(str(e) for e in payload.get("live_engines", []) or [])
        if not set(live_engines) <= _ALLOWED_LIVE_ENGINES:
            return JSONResponse({"error": "Unbekannte Live-Engine"}, status_code=400)
        reasoning = str(payload.get("reasoning_provider", "mock"))
        if reasoning not in _ALLOWED_REASONING:
            return JSONResponse({"error": "Unbekannter Reasoning-Provider"}, status_code=400)
        try:
            params = RunParams(
                domain=domain,
                offline=offline,
                explain=bool(payload.get("explain", True)),
                fix=bool(payload.get("fix", False)),
                learn=bool(payload.get("learn", False)),
                top_n=max(1, min(10, int(payload.get("top_n", 3)))),
                seed=int(payload.get("seed", 42)),
                n_proxy_ips=max(1, min(5, int(payload.get("n_proxy_ips", 5)))),
                live_engines=() if offline else live_engines,
                reasoning_provider=reasoning,
            )
        except (TypeError, ValueError):
            return JSONResponse({"error": "Ungueltige Zahlenwerte"}, status_code=400)
        run_id = manager.start(params)
        return JSONResponse({"run_id": run_id}, status_code=201)

    def run_stop(request: Request) -> JSONResponse:
        run_id = request.path_params["run_id"]
        stopped = manager.stop(run_id)
        if not stopped:
            return JSONResponse({"error": "Kein laufender Prozess fuer diesen Lauf"}, 404)
        return JSONResponse({"stopped": run_id})

    def run_delete(request: Request) -> JSONResponse:
        run_id = request.path_params["run_id"]
        record = storage.load_run(run_id)
        if record is None:
            return JSONResponse({"error": "Lauf unbekannt"}, status_code=404)
        if record.status == RunStatus.RUNNING or manager.is_alive(run_id):
            return JSONResponse({"error": "Laufender Lauf - zuerst stoppen"}, status_code=409)
        storage.delete_run(run_id)
        return JSONResponse({"deleted": run_id})

    def state(request: Request) -> JSONResponse:
        run = _selected_run(storage, request)
        if run is None:
            return JSONResponse({"run": None})
        probes = storage.load_probes(run.run_id)
        pages = storage.load_pages(run.run_id)
        report = storage.load_report(run.run_id)
        patterns = storage.load_pattern_report(run.run_id)
        audit = storage.load_audit_report(run.run_id)
        prompts = _prompt_texts(run.prompt_set_version)
        fix_plan = storage.load_fix_plan(run.run_id)
        deploy = storage.load_deploy_result(run.run_id)
        effect = storage.load_effect_report(run.run_id)
        # Nur die Baseline-Probes zaehlen als Fortschritt gegen die erwartete Matrix (Sprint 4:
        # die Re-Probe-Phase verdoppelt sonst die Zahl und laesst den Balken ueberlaufen).
        baseline_probes = [p for p in probes if p.phase.value == "baseline"]
        n_ips = len({probe.proxy_label or "" for probe in baseline_probes}) or cfg.n_proxy_ips
        expected = len(EngineId) * len(prompts) * n_ips
        fingerprint = (
            report_fingerprint(report, patterns, audit, fix_plan, effect)
            if report is not None
            else None
        )
        payload: dict[str, Any] = {
            "run": run.model_dump(mode="json"),
            "expected_probes": expected,
            "n_probes": len(baseline_probes),
            "n_pages": len(pages),
            "n_templates": len(patterns.templates) if patterns is not None else None,
            "n_findings": len(audit.findings) if audit is not None else None,
            "n_proposals": len(fix_plan.proposals) if fix_plan is not None else None,
            "deploy_status": deploy.status.value if deploy is not None else None,
            "n_hypotheses": len(effect.hypotheses) if effect is not None else None,
            "n_improved": effect.n_improved if effect is not None else None,
            "mean_delta": effect.mean_delta if effect is not None else None,
            "has_report": report is not None,
            "fingerprint": fingerprint,
            "dashboard_alive": manager.is_alive(run.run_id),
        }
        return JSONResponse(payload)

    def matrix(request: Request) -> JSONResponse:
        run = _selected_run(storage, request)
        if run is None:
            return JSONResponse({"run_id": None, "cells": []})
        # Baseline-Phase: die Re-Probe (Sprint 4) wuerde sonst jede Zelle verdoppeln und die
        # engine_rates ueber geboostete Probes verfaelschen (analog zum state-Endpoint).
        probes = storage.load_probes(run.run_id, ProbePhase.BASELINE)
        prompts = _prompt_texts(run.prompt_set_version)
        engines = [engine.value for engine in EngineId]
        cells = [
            {
                "prompt": probe.prompt_id,
                "engine": probe.engine_id.value,
                "proxy": probe.proxy_label or "",
                "cited": probe.target_cited,
                "rank": probe.target_rank,
                "status": probe.status.value,
            }
            for probe in probes
        ]
        rates: dict[str, float] = {}
        for engine in engines:
            hits = [cell for cell in cells if cell["engine"] == engine]
            cited = sum(1 for cell in hits if cell["cited"])
            rates[engine] = round(cited / len(hits), 3) if hits else 0.0
        return JSONResponse(
            {
                "run_id": run.run_id,
                "engines": engines,
                "proxies": _proxy_labels(probes, cfg.n_proxy_ips),
                "prompts": [{"id": pid, "text": text} for pid, text in sorted(prompts.items())],
                "cells": cells,
                "engine_rates": rates,
            }
        )

    def probe_detail(request: Request) -> JSONResponse:
        run = _selected_run(storage, request)
        if run is None:
            return JSONResponse({"error": "kein Lauf vorhanden"}, status_code=404)
        prompt = request.query_params.get("prompt", "")
        engine = request.query_params.get("engine", "")
        proxy = request.query_params.get("proxy", "")
        for probe in storage.load_probes(run.run_id, ProbePhase.BASELINE):
            if (
                probe.prompt_id == prompt
                and probe.engine_id.value == engine
                and (probe.proxy_label or "") == proxy
            ):
                payload = probe.model_dump(mode="json")
                payload["prompt_text"] = _prompt_texts(run.prompt_set_version).get(prompt, "")
                payload["target_domain"] = run.target_domain
                return JSONResponse(payload)
        return JSONResponse({"error": "Probe nicht gefunden"}, status_code=404)

    def pages(request: Request) -> JSONResponse:
        run = _selected_run(storage, request)
        if run is None:
            return JSONResponse({"pages": []})
        slim = [
            {
                "url": inventory.page.url,
                "title": inventory.page.title,
                "word_count": inventory.page.word_count,
                "n_h2": len(inventory.page.h2),
                "jsonld_types": list(inventory.schema_inventory.jsonld_types),
                "has_faq": inventory.schema_inventory.has_faq,
                "has_author": inventory.schema_inventory.has_author,
            }
            for inventory in storage.load_pages(run.run_id)
        ]
        return JSONResponse({"pages": slim})

    def results(request: Request) -> JSONResponse:
        run = _selected_run(storage, request)
        if run is None:
            return JSONResponse(
                {
                    "report": None,
                    "patterns": None,
                    "audit": None,
                    "fix_plan": None,
                    "deploy": None,
                    "effect": None,
                }
            )
        report = storage.load_report(run.run_id)
        patterns = storage.load_pattern_report(run.run_id)
        audit = storage.load_audit_report(run.run_id)
        fix_plan = storage.load_fix_plan(run.run_id)
        deploy = storage.load_deploy_result(run.run_id)
        effect = storage.load_effect_report(run.run_id)
        return JSONResponse(
            {
                "report": report.model_dump(mode="json") if report is not None else None,
                "patterns": patterns.model_dump(mode="json") if patterns is not None else None,
                "audit": audit.model_dump(mode="json") if audit is not None else None,
                "fix_plan": fix_plan.model_dump(mode="json") if fix_plan is not None else None,
                "deploy": deploy.model_dump(mode="json") if deploy is not None else None,
                "effect": effect.model_dump(mode="json") if effect is not None else None,
            }
        )

    routes = [
        Route("/", index),
        Route("/api/config", config),
        Route("/api/runs", runs_list, methods=["GET"]),
        Route("/api/runs", runs_start, methods=["POST"]),
        Route("/api/runs/{run_id}/stop", run_stop, methods=["POST"]),
        Route("/api/runs/{run_id}", run_delete, methods=["DELETE"]),
        Route("/api/state", state),
        Route("/api/matrix", matrix),
        Route("/api/probe", probe_detail),
        Route("/api/pages", pages),
        Route("/api/results", results),
    ]
    return Starlette(routes=routes)
