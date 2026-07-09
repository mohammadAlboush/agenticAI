"""Unit: WordPressPublisher — Doppel-Gate, Dry-Run ohne POST, Backup-vor-Write, Retry.

Alle HTTP-Aufrufe laufen ueber ``httpx.MockTransport`` (Projektregeln §5: nie echte
externe Calls in Tests). Das Transport-Log macht die harten Invarianten pruefbar:
0 POSTs im Dry-Run, Backup-Datei existiert VOR dem Write-POST, kein Secret im Detail.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from geo_audit_loop.adapters.publisher.wordpress import WordPressPublisher
from geo_audit_loop.domain.errors import ConfigError, DeployBlocked
from geo_audit_loop.domain.fix import (
    ApprovalDecision,
    ChangeType,
    DeployStatus,
    FixPlan,
    FixProposal,
)
from geo_audit_loop.domain.geo import Lever, PyramidLevel
from geo_audit_loop.domain.run import RunContext

FIXED = datetime(2026, 1, 1, 12, 0, 0)
Handler = Callable[[httpx.Request], httpx.Response]

BASE_URL = "https://site.example"
APP_PASSWORD = "app-pass-geheim-1234"
RAW_CONTENT = "Einleitung. ALT-AUSZUG steht hier. Schluss."
MODIFIED_BEFORE = "2026-01-01T10:00:00"
MODIFIED_AFTER = "2026-01-01T12:34:56"


def _clock() -> datetime:
    return FIXED


def _proposal(
    patch_id: str,
    *,
    change_type: ChangeType = ChangeType.INSERT_BLOCK,
    target_url: str = f"{BASE_URL}/nis2-faq/",
    current_excerpt: str = "",
    proposed_content: str = "Praegnanter Antwortblock (40-60 Woerter).",
) -> FixProposal:
    return FixProposal(
        patch_id=patch_id,
        finding_id=f"f-{patch_id}",
        target_url=target_url,
        lever=Lever.ANSWER_BLOCKS,
        pyramid_level=PyramidLevel.EXTRACTABILITY,
        change_type=change_type,
        current_excerpt=current_excerpt,
        proposed_content=proposed_content,
        rationale="Template t1 verlangt einen extrahierbaren Antwortblock.",
        confidence=0.8,
    )


def _plan(*proposals: FixProposal) -> FixPlan:
    return FixPlan(
        run_id="run-1",
        target_domain="site.example",
        generated_at=FIXED,
        prompt_version="v1",
        proposals=proposals,
    )


def _decision(patch_id: str, approved: bool) -> ApprovalDecision:
    return ApprovalDecision(
        patch_id=patch_id, run_id="run-1", approved=approved, reviewer="test", decided_at=FIXED
    )


def _ctx() -> RunContext:
    return RunContext(
        run_id="run-1",
        target_domain="site.example",
        started_at=FIXED,
        seed=42,
        prompt_set_version="v1",
        config_hash="abc",
    )


def _make_handler(
    log: list[tuple[str, str]],
    *,
    raw: str = RAW_CONTENT,
    slug: str = "nis2-faq",
    post_id: int = 7,
    collection: str = "posts",
    fail_posts: int = 0,
    on_post: Callable[[httpx.Request], None] | None = None,
) -> Handler:
    """Simulierte WP-REST-API: Slug-Resolve, Edit-Kontext, Write-POST (konfigurierbare 503s)."""
    state = {"failed": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        log.append((request.method, request.url.path))
        path = request.url.path
        if request.method == "GET" and path in ("/wp-json/wp/v2/posts", "/wp-json/wp/v2/pages"):
            hit = path.endswith(collection) and request.url.params.get("slug") == slug
            return httpx.Response(200, json=[{"id": post_id, "slug": slug}] if hit else [])
        if request.method == "GET" and path == f"/wp-json/wp/v2/{collection}/{post_id}":
            payload = {
                "id": post_id,
                "modified": MODIFIED_BEFORE,
                "content": {"raw": raw, "rendered": f"<p>{raw}</p>"},
            }
            return httpx.Response(200, json=payload)
        if request.method == "POST" and path == f"/wp-json/wp/v2/{collection}/{post_id}":
            if state["failed"] < fail_posts:
                state["failed"] += 1
                return httpx.Response(503, json={})
            if on_post is not None:
                on_post(request)
            return httpx.Response(200, json={"id": post_id, "modified": MODIFIED_AFTER})
        return httpx.Response(404, json={"code": "rest_no_route"})

    return handler


def _publisher(
    handler: Handler, tmp_path: Path, *, allow_remote: bool = True, attempts: int = 3
) -> WordPressPublisher:
    return WordPressPublisher(
        base_url=BASE_URL,
        username="admin",
        app_password=APP_PASSWORD,
        runs_dir=tmp_path,
        allow_remote=allow_remote,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
        max_attempts=attempts,
        base_delay_s=0.0,
        max_delay_s=0.0,
        clock=_clock,
        sleep=lambda _d: None,
    )


def _posts(log: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [entry for entry in log if entry[0] == "POST"]


# --- Konstruktor-Gates -----------------------------------------------------


@pytest.mark.parametrize(
    ("base_url", "username", "app_password"),
    [(None, "admin", APP_PASSWORD), (BASE_URL, None, APP_PASSWORD), (BASE_URL, "admin", None)],
)
def test_missing_credentials_raise_config_error(
    base_url: str | None, username: str | None, app_password: str | None, tmp_path: Path
) -> None:
    with pytest.raises(ConfigError):
        WordPressPublisher(
            base_url=base_url,
            username=username,
            app_password=app_password,
            runs_dir=tmp_path,
        )


def test_blocked_without_allow_remote_makes_zero_calls(tmp_path: Path) -> None:
    log: list[tuple[str, str]] = []
    pub = _publisher(_make_handler(log), tmp_path, allow_remote=False)
    decisions = {"px-a": _decision("px-a", True)}
    with pytest.raises(DeployBlocked):
        pub.publish(_plan(_proposal("px-a")), decisions, run_context=_ctx(), dry_run=False)
    assert log == []  # Gate greift VOR jedem HTTP-Aufruf


# --- Dry-Run ----------------------------------------------------------------


def test_dry_run_resolves_but_never_posts(tmp_path: Path) -> None:
    log: list[tuple[str, str]] = []
    pub = _publisher(_make_handler(log), tmp_path)
    decisions = {"px-a": _decision("px-a", True)}
    result = pub.publish(_plan(_proposal("px-a")), decisions, run_context=_ctx(), dry_run=True)
    assert _posts(log) == []  # KEIN einziger POST im Dry-Run
    assert result.status is DeployStatus.DRY_RUN
    assert result.dry_run is True
    assert result.applied_patch_ids == ("px-a",)  # validiert, nicht geschrieben
    assert not (tmp_path / "run-1").exists()  # auch kein Backup angelegt


# --- Backup-vor-Write -------------------------------------------------------


def test_backup_file_exists_before_write_post(tmp_path: Path) -> None:
    backup_file = tmp_path / "run-1" / "backups" / "px-a.json"
    seen = {"backup_before_post": False}

    def on_post(_request: httpx.Request) -> None:
        # Reihenfolge-Assertion: zum Zeitpunkt des Write-POST liegt das Backup schon auf Platte.
        seen["backup_before_post"] = backup_file.exists()

    log: list[tuple[str, str]] = []
    pub = _publisher(_make_handler(log, on_post=on_post), tmp_path)
    decisions = {"px-a": _decision("px-a", True)}
    result = pub.publish(_plan(_proposal("px-a")), decisions, run_context=_ctx(), dry_run=False)
    assert seen["backup_before_post"] is True
    assert result.status is DeployStatus.APPLIED
    assert result.dry_run is False
    assert result.artifact_path == str(tmp_path / "run-1" / "backups")
    saved = json.loads(backup_file.read_text("utf-8"))
    assert saved["content"]["raw"] == RAW_CONTENT  # Original-Inhalt gesichert


# --- HITL-Invariante ---------------------------------------------------------


def test_only_approved_patches_applied(tmp_path: Path) -> None:
    log: list[tuple[str, str]] = []
    pub = _publisher(_make_handler(log), tmp_path)
    plan = _plan(_proposal("px-a"), _proposal("px-b"), _proposal("px-c"))
    decisions = {"px-a": _decision("px-a", True), "px-b": _decision("px-b", False)}
    # px-c hat GAR KEINE Entscheidung -> muss uebersprungen werden (HITL-Gate).
    result = pub.publish(plan, decisions, run_context=_ctx(), dry_run=False)
    assert result.applied_patch_ids == ("px-a",)
    assert set(result.skipped_patch_ids) == {"px-b", "px-c"}
    assert len(_posts(log)) == 1  # genau ein Write, fuer den freigegebenen Patch


# --- ChangeTypes -------------------------------------------------------------


def test_rewrite_without_excerpt_match_is_skipped(tmp_path: Path) -> None:
    log: list[tuple[str, str]] = []
    pub = _publisher(_make_handler(log), tmp_path)
    proposal = _proposal(
        "px-a", change_type=ChangeType.REWRITE_BLOCK, current_excerpt="NICHT IM INHALT"
    )
    decisions = {"px-a": _decision("px-a", True)}
    result = pub.publish(_plan(proposal), decisions, run_context=_ctx(), dry_run=False)
    assert result.applied_patch_ids == ()
    assert result.skipped_patch_ids == ("px-a",)
    assert _posts(log) == []  # ohne exakten Match wird NICHT geschrieben
    assert "px-a" in result.detail
    assert "current_excerpt" in result.detail


def test_rewrite_with_match_replaces_excerpt(tmp_path: Path) -> None:
    bodies: list[str] = []

    def on_post(request: httpx.Request) -> None:
        bodies.append(json.loads(request.content)["content"])

    log: list[tuple[str, str]] = []
    pub = _publisher(_make_handler(log, on_post=on_post), tmp_path)
    proposal = _proposal(
        "px-a",
        change_type=ChangeType.REWRITE_BLOCK,
        current_excerpt="ALT-AUSZUG steht hier.",
        proposed_content="NEUER Auszug steht hier.",
    )
    decisions = {"px-a": _decision("px-a", True)}
    result = pub.publish(_plan(proposal), decisions, run_context=_ctx(), dry_run=False)
    assert result.status is DeployStatus.APPLIED
    assert bodies == ["Einleitung. NEUER Auszug steht hier. Schluss."]


def test_insert_block_prepends_content(tmp_path: Path) -> None:
    bodies: list[str] = []

    def on_post(request: httpx.Request) -> None:
        bodies.append(json.loads(request.content)["content"])

    log: list[tuple[str, str]] = []
    pub = _publisher(_make_handler(log, on_post=on_post), tmp_path)
    decisions = {"px-a": _decision("px-a", True)}
    pub.publish(_plan(_proposal("px-a")), decisions, run_context=_ctx(), dry_run=False)
    assert bodies[0].startswith("Praegnanter Antwortblock")
    assert bodies[0].endswith(RAW_CONTENT)  # Bestand bleibt vollstaendig erhalten


def test_add_schema_appends_jsonld_script(tmp_path: Path) -> None:
    bodies: list[str] = []

    def on_post(request: httpx.Request) -> None:
        bodies.append(json.loads(request.content)["content"])

    log: list[tuple[str, str]] = []
    pub = _publisher(_make_handler(log, on_post=on_post), tmp_path)
    proposal = _proposal(
        "px-a",
        change_type=ChangeType.ADD_SCHEMA,
        proposed_content='{"@context": "https://schema.org", "@type": "FAQPage"}',
    )
    decisions = {"px-a": _decision("px-a", True)}
    pub.publish(_plan(proposal), decisions, run_context=_ctx(), dry_run=False)
    assert bodies[0].startswith(RAW_CONTENT)
    assert '<script type="application/ld+json">' in bodies[0]
    assert '"FAQPage"' in bodies[0]


@pytest.mark.parametrize("change_type", [ChangeType.ADD_HEADING, ChangeType.META_UPDATE])
def test_unsupported_change_types_skipped_without_http(
    change_type: ChangeType, tmp_path: Path
) -> None:
    log: list[tuple[str, str]] = []
    pub = _publisher(_make_handler(log), tmp_path)
    decisions = {"px-a": _decision("px-a", True)}
    result = pub.publish(
        _plan(_proposal("px-a", change_type=change_type)),
        decisions,
        run_context=_ctx(),
        dry_run=False,
    )
    assert result.applied_patch_ids == ()
    assert result.skipped_patch_ids == ("px-a",)
    assert log == []  # konservativ: gar kein HTTP fuer nicht unterstuetzte Typen
    assert change_type.value in result.detail


# --- Slug-Resolve ------------------------------------------------------------


def test_unresolvable_slug_is_skipped(tmp_path: Path) -> None:
    log: list[tuple[str, str]] = []
    pub = _publisher(_make_handler(log, slug="anderer-slug"), tmp_path)
    decisions = {"px-a": _decision("px-a", True)}
    result = pub.publish(_plan(_proposal("px-a")), decisions, run_context=_ctx(), dry_run=False)
    assert result.applied_patch_ids == ()
    assert result.skipped_patch_ids == ("px-a",)
    assert _posts(log) == []
    assert "aufloesbar" in result.detail


def test_pages_fallback_resolves_and_writes_page(tmp_path: Path) -> None:
    log: list[tuple[str, str]] = []
    pub = _publisher(_make_handler(log, collection="pages", post_id=9), tmp_path)
    decisions = {"px-a": _decision("px-a", True)}
    result = pub.publish(_plan(_proposal("px-a")), decisions, run_context=_ctx(), dry_run=False)
    assert result.status is DeployStatus.APPLIED
    assert _posts(log) == [("POST", "/wp-json/wp/v2/pages/9")]
    assert result.artifact_ref == f"wp:page/9@{MODIFIED_AFTER}"


# --- Retry / Fehlerpfade -----------------------------------------------------


def test_write_5xx_is_retried_then_succeeds(tmp_path: Path) -> None:
    log: list[tuple[str, str]] = []
    pub = _publisher(_make_handler(log, fail_posts=1), tmp_path)
    decisions = {"px-a": _decision("px-a", True)}
    result = pub.publish(_plan(_proposal("px-a")), decisions, run_context=_ctx(), dry_run=False)
    assert result.status is DeployStatus.APPLIED
    assert len(_posts(log)) == 2  # 503 -> Retry -> 200
    assert result.artifact_ref == f"wp:post/7@{MODIFIED_AFTER}"


def test_persistent_5xx_marks_failed_without_raising(tmp_path: Path) -> None:
    log: list[tuple[str, str]] = []
    pub = _publisher(_make_handler(log, fail_posts=99), tmp_path, attempts=3)
    decisions = {"px-a": _decision("px-a", True)}
    result = pub.publish(_plan(_proposal("px-a")), decisions, run_context=_ctx(), dry_run=False)
    assert result.status is DeployStatus.FAILED
    assert result.applied_patch_ids == ()
    assert result.skipped_patch_ids == ("px-a",)
    assert len(_posts(log)) == 3  # max_attempts ausgeschoepft
    assert result.dry_run is True  # nichts extern geaendert -> IndexNow-Gate bleibt zu


# --- Secrets -----------------------------------------------------------------


def test_no_secret_in_deploy_result_detail(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization", "").startswith("Basic ")  # Auth gesetzt
        return httpx.Response(401, json={"code": "rest_forbidden"})

    pub = _publisher(handler, tmp_path)
    decisions = {"px-a": _decision("px-a", True)}
    result = pub.publish(_plan(_proposal("px-a")), decisions, run_context=_ctx(), dry_run=False)
    assert result.status is DeployStatus.FAILED
    assert APP_PASSWORD not in result.detail
    assert APP_PASSWORD not in str(result.model_dump())
