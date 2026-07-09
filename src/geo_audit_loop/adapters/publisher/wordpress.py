"""WordPress-Publisher: wendet freigegebene Patches ueber die WP-REST-API an (Live-Deploy).

Sicherheitsnetz (Projektregeln §6, HITL hart):

1. **HITL** — nur Patches mit ``approved=True`` werden ueberhaupt betrachtet
   (``partition_by_approval``); alle anderen landen in ``skipped_patch_ids``.
2. **Konstruktor-Gate** — ohne ``allow_remote=True`` wirft ``publish()`` ``DeployBlocked``
   (Invariante des frueheren Remote-Stubs bleibt erhalten).
3. **Dry-Run-Default** — ``dry_run=True`` loest Slugs nur auf und validiert; es wird
   KEIN einziger Schreib-POST ausgefuehrt (``DeployResult.status=DRY_RUN``).
4. **Backup vor Write** — vor jedem POST wird der Edit-Kontext (``content.raw``) als JSON
   nach ``{runs_dir}/<run_id>/backups/<patch_id>.json`` gesichert; ohne Backup kein Write.
5. **Konservative ChangeTypes** — INSERT_BLOCK (Block voranstellen), REWRITE_BLOCK (nur bei
   exakter ``current_excerpt``-Uebereinstimmung, sonst skip), ADD_SCHEMA (JSON-LD-Script
   anhaengen); ADD_HEADING/META_UPDATE werden mit Detail uebersprungen.

HTTP-Fehler werfen nie aus ``publish()`` heraus: betroffene Patches werden mit Detail
uebersprungen. Das gilt auch fuer Nicht-JSON-Antworten (klassisch: PHP-Warnung vor dem
JSON-Body bei HTTP 200) — nach einem erfolgreichen Write-POST zaehlt der Patch dabei
weiterhin als angewandt (der Write ist nicht idempotent!). 5xx/Transportfehler (und 429 —
eigene Site, begrenzt unkritisch) werden mit Backoff wiederholt (``retry_call``).
Credentials erscheinen nie im ``DeployResult``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

import httpx

from geo_audit_loop.adapters.publisher import partition_by_approval
from geo_audit_loop.config.constants import (
    BACKUPS_SUBDIR,
    RETRY_BASE_DELAY_S,
    RETRY_MAX_ATTEMPTS,
    RETRY_MAX_DELAY_S,
)
from geo_audit_loop.domain.errors import ConfigError, DeployBlocked
from geo_audit_loop.domain.fix import (
    ApprovalDecision,
    ChangeType,
    DeployResult,
    DeployStatus,
    FixPlan,
    FixProposal,
)
from geo_audit_loop.domain.run import RunContext
from geo_audit_loop.observability.retry import retry_call

ClientFactory = Callable[[], httpx.Client]

_RETRY_STATUS: Final = frozenset({429, 500, 502, 503, 504})
_WP_API_PREFIX: Final = "/wp-json/wp/v2"
_COLLECTIONS: Final = ("posts", "pages")  # Slug-Resolve: posts zuerst, dann pages (Fallback)
_UNSUPPORTED_CHANGE_TYPES: Final = frozenset({ChangeType.ADD_HEADING, ChangeType.META_UPDATE})
_DEFAULT_TIMEOUT_S: Final = 30.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _RetryableStatus(Exception):
    """Interner Marker fuer wiederholbare HTTP-Status (429/5xx)."""


@dataclass(frozen=True)
class _PatchOutcome:
    """Ergebnis eines einzelnen Patch-Versuchs (intern, kein Agenten-Contract)."""

    applied: bool
    failed: bool
    note: str
    ref: str | None = None
    backup_written: bool = False


class WordPressPublisher:
    """Erfuellt ``PublisherPort`` — echter WP-REST-Deploy hinter Doppel-Gate + Backup."""

    name = "wordpress"

    def __init__(
        self,
        *,
        base_url: str | None,
        username: str | None,
        app_password: str | None,
        runs_dir: Path,
        allow_remote: bool = False,
        client_factory: ClientFactory | None = None,
        max_attempts: int = RETRY_MAX_ATTEMPTS,
        base_delay_s: float = RETRY_BASE_DELAY_S,
        max_delay_s: float = RETRY_MAX_DELAY_S,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not base_url:
            raise ConfigError("GEO_WP_BASE_URL fehlt - WordPress-Publisher nicht nutzbar")
        if not username or not app_password:
            raise ConfigError(
                "WP_USERNAME/WP_APP_PASSWORD fehlen - WordPress-Publisher nicht nutzbar"
            )
        self._base_url = base_url.rstrip("/")
        self._auth = httpx.BasicAuth(username, app_password)
        self._runs_dir = runs_dir
        self._allow_remote = allow_remote
        self._client_factory = client_factory or self._default_client_factory
        self._max_attempts = max_attempts
        self._base_delay_s = base_delay_s
        self._max_delay_s = max_delay_s
        self._clock = clock if clock is not None else _utc_now
        self._sleep = sleep

    def _default_client_factory(self) -> httpx.Client:
        return httpx.Client(timeout=_DEFAULT_TIMEOUT_S)

    def publish(
        self,
        plan: FixPlan,
        decisions: Mapping[str, ApprovalDecision],
        *,
        run_context: RunContext,
        dry_run: bool = True,
    ) -> DeployResult:
        """Wendet ausschliesslich freigegebene Patches remote an; uebrige werden uebersprungen.

        Ohne ``allow_remote=True`` (Konstruktor-Gate) wird ``DeployBlocked`` geworfen, bevor
        irgendein HTTP-Aufruf passiert. Bei ``dry_run=True`` wird nur aufgeloest/validiert
        (GETs erlaubt, kein einziger POST). HTTP-Fehler einzelner Patches werfen nie —
        sie landen als Detail in ``skipped_patch_ids``/``detail``.
        """
        if not self._allow_remote:
            raise DeployBlocked(
                f"{self.name}: Remote-Publishing blockiert - allow_remote-Flag fehlt "
                "(Doppel-Gate, Projektregeln §6)."
            )
        approved, hitl_skipped = partition_by_approval(plan.proposals, decisions)
        backup_dir = self._runs_dir / plan.run_id / BACKUPS_SUBDIR

        outcomes: list[tuple[FixProposal, _PatchOutcome]] = []
        client = self._client_factory()
        try:
            for proposal in approved:
                outcomes.append(
                    (proposal, self._apply_patch(client, proposal, backup_dir, dry_run))
                )
        finally:
            client.close()

        applied_ids = tuple(p.patch_id for p, o in outcomes if o.applied)
        skipped_ids = tuple(p.patch_id for p in hitl_skipped) + tuple(
            p.patch_id for p, o in outcomes if not o.applied
        )
        had_failure = any(o.failed for _p, o in outcomes)
        any_backup = any(o.backup_written for _p, o in outcomes)
        artifact_ref = next((o.ref for _p, o in reversed(outcomes) if o.ref is not None), None)

        if dry_run:
            status = DeployStatus.DRY_RUN
        elif applied_ids:
            status = DeployStatus.APPLIED
        elif had_failure:
            status = DeployStatus.FAILED
        else:
            status = DeployStatus.DRY_RUN  # nichts extern geschrieben

        mode = "Dry-Run (kein Write)" if dry_run else "Live-Deploy"
        notes = " | ".join(f"{p.patch_id}: {o.note}" for p, o in outcomes)
        detail = f"{mode}: {len(applied_ids)} angewandt, {len(skipped_ids)} uebersprungen." + (
            f" {notes}" if notes else ""
        )
        return DeployResult(
            run_id=plan.run_id,
            target_domain=plan.target_domain,
            generated_at=self._clock(),
            publisher=self.name,
            # dry_run=False NUR, wenn tatsaechlich extern geschrieben wurde (IndexNow-Gate).
            dry_run=bool(dry_run or not applied_ids),
            applied_patch_ids=applied_ids,
            skipped_patch_ids=skipped_ids,
            status=status,
            artifact_path=str(backup_dir) if any_backup else None,
            artifact_ref=artifact_ref,
            detail=detail,
        )

    def _apply_patch(
        self, client: httpx.Client, proposal: FixProposal, backup_dir: Path, dry_run: bool
    ) -> _PatchOutcome:
        """Fuehrt Resolve -> (Dry-Run-Stopp) -> Backup -> Transform -> POST fuer EINEN Patch aus."""
        slug = _slug_from_url(proposal.target_url)
        if slug is None:
            return _PatchOutcome(False, False, "uebersprungen: kein Slug aus target_url ableitbar")
        if proposal.change_type in _UNSUPPORTED_CHANGE_TYPES:
            return _PatchOutcome(
                False,
                False,
                f"uebersprungen: change_type '{proposal.change_type.value}' wird remote "
                "konservativ nicht angewandt",
            )
        try:
            resolved = self._resolve(client, slug)
        except (httpx.HTTPError, _RetryableStatus) as exc:
            return _PatchOutcome(False, True, f"fehlgeschlagen: Slug-Resolve ({exc})")
        except ValueError:  # json.JSONDecodeError: z.B. PHP-Warnung vor dem JSON-Body
            return _PatchOutcome(False, True, "fehlgeschlagen: Slug-Resolve (Antwort kein JSON)")
        if resolved is None:
            return _PatchOutcome(
                False, False, f"uebersprungen: Slug '{slug}' weder als Post noch Page aufloesbar"
            )
        collection, post_id = resolved
        if dry_run:
            return _PatchOutcome(
                True, False, f"validiert ({collection}/{post_id}, Dry-Run: kein Write)"
            )

        # Backup VOR Write: Edit-Kontext (content.raw) lesen und lokal sichern.
        edit_url = f"{self._base_url}{_WP_API_PREFIX}/{collection}/{post_id}"
        try:
            edit_data: Any = self._send(  # JSON-Payload ist schemafrei (Any gerechtfertigt)
                client, "GET", edit_url, params={"context": "edit"}
            ).json()
        except (httpx.HTTPError, _RetryableStatus) as exc:
            return _PatchOutcome(
                False, True, f"fehlgeschlagen: Edit-Kontext nicht lesbar ({exc}) => kein Backup"
            )
        except ValueError:  # json.JSONDecodeError: kein Backup moeglich => kein Write
            return _PatchOutcome(
                False, True, "fehlgeschlagen: Edit-Kontext kein JSON => kein Backup"
            )
        raw = _extract_raw(edit_data)
        if raw is None:
            return _PatchOutcome(
                False, False, "uebersprungen: content.raw fehlt im Edit-Kontext => kein Backup"
            )
        new_content = _transform(proposal, raw)
        if new_content is None:
            return _PatchOutcome(
                False, False, "uebersprungen: current_excerpt nicht exakt im Live-Inhalt gefunden"
            )
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            (backup_dir / f"{proposal.patch_id}.json").write_text(
                json.dumps(edit_data, ensure_ascii=False, indent=2), "utf-8"
            )
        except OSError as exc:
            return _PatchOutcome(
                False, True, f"fehlgeschlagen: Backup nicht schreibbar ({exc}) => kein Write"
            )

        try:
            response = self._send(client, "POST", edit_url, json_body={"content": new_content})
        except (httpx.HTTPError, _RetryableStatus) as exc:
            return _PatchOutcome(
                False, True, f"fehlgeschlagen: Write-POST ({exc})", backup_written=True
            )
        try:
            modified = _extract_modified(response.json())
        except ValueError:  # json.JSONDecodeError
            # Der Write WAR erfolgreich (nicht idempotent!) — eine Nicht-JSON-Antwort
            # (z.B. PHP-Warnung vor dem Body) darf ihn nicht als Fehler werten, sonst
            # wuerde ein Wiederholungslauf den Block ein zweites Mal voranstellen.
            modified = "unbekannt"
        ref = f"wp:{collection.removesuffix('s')}/{post_id}@{modified}"
        return _PatchOutcome(True, False, f"angewandt ({ref})", ref=ref, backup_written=True)

    def _resolve(self, client: httpx.Client, slug: str) -> tuple[str, int] | None:
        """Loest einen Slug zu (collection, id) auf — posts zuerst, pages als Fallback."""
        for collection in _COLLECTIONS:
            url = f"{self._base_url}{_WP_API_PREFIX}/{collection}"
            items: Any = self._send(client, "GET", url, params={"slug": slug}).json()  # JSON: Any
            if not isinstance(items, list) or not items:
                continue
            first = items[0]
            if isinstance(first, dict):
                post_id = first.get("id")
                if isinstance(post_id, int):
                    return collection, post_id
        return None

    def _send(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """HTTP mit Basic Auth + Backoff-Retry auf 429/5xx/Transportfehler."""

        def call() -> httpx.Response:
            response = client.request(method, url, params=params, json=json_body, auth=self._auth)
            if response.status_code in _RETRY_STATUS:
                raise _RetryableStatus(f"HTTP {response.status_code}")
            response.raise_for_status()
            return response

        return retry_call(
            call,
            max_attempts=self._max_attempts,
            base_delay_s=self._base_delay_s,
            max_delay_s=self._max_delay_s,
            retry_on=(_RetryableStatus, httpx.TransportError),
            sleep=self._sleep,
        )


def _slug_from_url(url: str) -> str | None:
    """Letztes nicht-leeres Pfadsegment der ``target_url`` = WordPress-Slug."""
    segments = [segment for segment in urlsplit(url).path.split("/") if segment]
    return segments[-1] if segments else None


def _extract_raw(data: Any) -> str | None:  # JSON-Payload ist schemafrei (Any gerechtfertigt)
    """Liest ``content.raw`` aus dem Edit-Kontext; ``None`` wenn nicht vorhanden/kein String."""
    content = data.get("content") if isinstance(data, dict) else None
    raw = content.get("raw") if isinstance(content, dict) else None
    return raw if isinstance(raw, str) else None


def _extract_modified(data: Any) -> str:  # JSON-Payload ist schemafrei (Any gerechtfertigt)
    """Liest den ``modified``-Zeitstempel der Write-Antwort (fuer ``artifact_ref``)."""
    modified = data.get("modified") if isinstance(data, dict) else None
    return modified if isinstance(modified, str) else "unbekannt"


def _transform(proposal: FixProposal, raw: str) -> str | None:
    """Wendet den ChangeType konservativ auf den Roh-Inhalt an; ``None`` = nicht anwendbar."""
    if proposal.change_type is ChangeType.INSERT_BLOCK:
        return f"{proposal.proposed_content}\n\n{raw}"
    if proposal.change_type is ChangeType.REWRITE_BLOCK:
        if proposal.current_excerpt not in raw:
            return None
        return raw.replace(proposal.current_excerpt, proposal.proposed_content, 1)
    if proposal.change_type is ChangeType.ADD_SCHEMA:
        script = proposal.proposed_content
        if "<script" not in script:
            script = f'<script type="application/ld+json">{script}</script>'
        return f"{raw}\n{script}"
    return None  # unsupported ChangeTypes werden bereits vorher uebersprungen
