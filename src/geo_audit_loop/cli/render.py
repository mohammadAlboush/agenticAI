"""Rich-Rendering der Run-Ergebnisse fuer die CLI (Praesentationsschicht).

Reine Render-Funktionen: sie erhalten eine ``rich.console.Console`` plus fertige
Domain-Contracts und schreiben formatierte Ausgabe — kein anderes I/O, keine
Geschaeftslogik. Das Layout ist auf ~100 Spalten ausgelegt (Demo-Aufnahme).
"""

from __future__ import annotations

from typing import Final
from urllib.parse import urlsplit

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from geo_audit_loop.domain.audit import AuditReport, Severity
from geo_audit_loop.domain.competitive import ShareOfVoiceReport
from geo_audit_loop.domain.coverage import INTENT_LABELS, CoverageReport
from geo_audit_loop.domain.effect import EffectDirection, EffectReport
from geo_audit_loop.domain.entity import EntityGraphReport
from geo_audit_loop.domain.findings import TopFlopEntry, TopFlopReport, VisibilityBand
from geo_audit_loop.domain.fix import (
    ApprovalDecision,
    ChangeType,
    DeployResult,
    DeployStatus,
    FixPlan,
)
from geo_audit_loop.domain.geo import LEVER_LABELS, PYRAMID_LABELS
from geo_audit_loop.domain.templates import PatternReport
from geo_audit_loop.domain.trend import TREND_DIRECTION_LABELS, TrendDirection, TrendReport
from geo_audit_loop.observability.cost import CostSnapshot

#: Markenfarben (an das Folien-Deck angelehnt, auf dunklem Terminal lesbar).
ACCENT: Final = "#8bd13d"
ACCENT_DIM: Final = "#4f7d1a"
AMBER: Final = "#e4b73f"
RED: Final = "#ef6a5c"
GREY: Final = "grey62"

_SEVERITY_STYLES: Final[dict[Severity, str]] = {
    Severity.CRITICAL: "bold white on #8a241a",
    Severity.HIGH: "bold white on #a8392c",
    Severity.MEDIUM: "bold black on #e4b73f",
    Severity.LOW: "bold black on grey62",
}

#: Achtel-Bloecke fuer feinaufgeloeste Balken.
_BLOCKS: Final = " ▏▎▍▌▋▊▉█"

#: Kurzlabels der Aenderungsarten (Sprint 3).
_CHANGE_TYPE_LABELS: Final[dict[ChangeType, str]] = {
    ChangeType.INSERT_BLOCK: "Block +",
    ChangeType.REWRITE_BLOCK: "Umschreiben",
    ChangeType.ADD_SCHEMA: "Schema +",
    ChangeType.ADD_HEADING: "Ueberschrift +",
    ChangeType.META_UPDATE: "Meta",
}

#: Badge-Stile der Deploy-Status (Sprint 3).
_DEPLOY_STYLES: Final[dict[DeployStatus, str]] = {
    DeployStatus.DRY_RUN: f"bold black on {ACCENT}",
    DeployStatus.APPLIED: f"bold black on {ACCENT}",
    DeployStatus.BLOCKED: "bold black on #e4b73f",
    DeployStatus.FAILED: "bold white on #a8392c",
}

#: Badges der Effekt-Richtung (Sprint 4).
_DIRECTION_BADGES: Final[dict[EffectDirection, tuple[str, str]]] = {
    EffectDirection.IMPROVED: ("▲ BESSER", f"bold black on {ACCENT}"),
    EffectDirection.REGRESSED: ("▼ SCHLECHTER", "bold white on #a8392c"),
    EffectDirection.UNCHANGED: ("— GLEICH", "bold black on grey62"),
}


def _bar(fraction: float, width: int, style: str) -> Text:
    """Baut einen Balken der Laenge ``width`` Zellen, gefuellt zu ``fraction``."""
    clamped = max(0.0, min(1.0, fraction))
    cells = clamped * width
    full = int(cells)
    eighths = round((cells - full) * 8)
    if eighths == 8:
        full, eighths = full + 1, 0
    body = "█" * full + (_BLOCKS[eighths] if eighths else "")
    bar = Text(body.ljust(width), style=style)
    return bar


def _short_url(url: str) -> str:
    """Kuerzt eine URL auf ihren Pfad — die Domain steht bereits im Header-Panel."""
    path = urlsplit(url).path
    return path if path else url


def _severity_badge(severity: Severity) -> Text:
    """Farbiges Badge wie `` HIGH `` fuer den Schweregrad."""
    return Text(f" {severity.value.upper()} ", style=_SEVERITY_STYLES[severity])


def render_header(
    console: Console,
    *,
    domain: str,
    run_id: str,
    seed: int,
    offline: bool,
    prompt_version: str,
    top_n: int,
    stage_label: str = "Sprint 2 — Learning",
) -> None:
    """Rendert das Kopf-Panel mit Run-Metadaten."""
    mode = (
        Text(" OFFLINE · DETERMINISTISCH ", style=f"bold black on {ACCENT}")
        if offline
        else Text(" LIVE ", style=f"bold black on {AMBER}")
    )
    title = Text()
    title.append("geo-audit-loop", style=f"bold {ACCENT}")
    title.append(f" · {stage_label}", style="bold")
    meta = Text()
    meta.append(domain, style="bold")
    meta.append("   ")
    meta.append_text(mode)
    meta.append(f"   Seed {seed}", style=GREY)
    sub = Text(
        f"run {run_id} · Prompts {prompt_version} · Top-N {top_n}",
        style=GREY,
    )
    grid = Table.grid(padding=(0, 0))
    grid.add_column()
    grid.add_row(title)
    grid.add_row(meta)
    grid.add_row(sub)
    console.print(Panel(grid, border_style=ACCENT_DIM, padding=(1, 2)))


def render_topflop(console: Console, report: TopFlopReport) -> None:
    """Rendert Akt 1 (WAS wird zitiert?): die Top/Flop-Sichtbarkeitstabelle."""
    console.print()
    console.rule(
        Text("WAS — GEO-Sichtbarkeit", style=f"bold {ACCENT}"),
        style=ACCENT_DIM,
        align="left",
    )
    n_distinct = sum(
        1 for entry in (*report.top, *report.flop) if entry.band is not VisibilityBand.TYPICAL
    )
    table = Table(
        show_header=True,
        header_style=f"bold {GREY}",
        border_style="grey30",
        caption=(
            f"{report.n_probes} Probes · {report.n_pages} Seiten · "
            f"Domain-Schnitt {report.field_citation_rate:.2f} · "
            f"{n_distinct} Seiten statistisch abgesetzt (95%-KI ohne Schnitt)"
        ),
        caption_style=GREY,
        expand=True,
    )
    table.add_column("", width=6)
    table.add_column("#", justify="right", width=3)
    table.add_column("URL", ratio=2, no_wrap=True)
    table.add_column("Zitationen", justify="right", width=10)
    table.add_column("Rate", justify="right", width=6)
    table.add_column("95%-KI", justify="center", width=15)
    table.add_column("", width=10)

    scale = max(
        (entry.citation_rate for entry in (*report.top, *report.flop)),
        default=0.0,
    )

    def _row(marker: Text, entry: TopFlopEntry, bar_style: str) -> None:
        fraction = entry.citation_rate / scale if scale > 0 else 0.0
        # KI-Farbe zeigt die statistische Absetzung: abgesetzt = Akzent, im Rauschen = grau.
        ci_style = GREY if entry.band is VisibilityBand.TYPICAL else bar_style
        table.add_row(
            marker,
            str(entry.position),
            Text(_short_url(entry.url), style="bold"),
            f"{entry.citation_count}x",
            f"{entry.citation_rate:.2f}",
            Text(f"[{entry.rate_ci_low:.2f}, {entry.rate_ci_high:.2f}]", style=ci_style),
            _bar(fraction, 10, bar_style),
        )

    for entry in report.top:
        _row(Text("▲ TOP", style=f"bold {ACCENT}"), entry, ACCENT)
    if report.top and report.flop:
        table.add_section()
    for entry in report.flop:
        _row(Text("▼ FLOP", style=f"bold {RED}"), entry, RED)
    console.print(table)


def render_share_of_voice(console: Console, report: ShareOfVoiceReport) -> None:
    """Rendert die Wettbewerbslandschaft (WER gewinnt die Zitate?): der Share of Voice."""
    console.print()
    console.rule(
        Text("WER — Wettbewerbs-Sichtbarkeit (Share of Voice)", style=f"bold {ACCENT}"),
        style=ACCENT_DIM,
        align="left",
    )
    if not report.shares:
        console.print(Text("Keine zitierten Domains gemessen.", style=GREY))
        return
    rank_txt = f"#{report.target_rank}" if report.target_rank is not None else "nicht zitiert"
    table = Table(
        show_header=True,
        header_style=f"bold {GREY}",
        border_style="grey30",
        caption=(
            f"{report.n_probes} Probes · Zieldomain {rank_txt} "
            f"({report.target_share:.0%} der Antworten) · Anteil = Antworten mit dieser Quelle"
        ),
        caption_style=GREY,
        expand=True,
    )
    table.add_column("#", justify="right", width=3)
    table.add_column("Domain", ratio=2, no_wrap=True)
    table.add_column("Antworten", justify="right", width=10)
    table.add_column("Share", justify="right", width=6)
    table.add_column("", width=18)
    scale = max((s.citation_rate for s in report.shares), default=0.0)
    for share in report.shares:
        is_t = share.is_target
        domain = Text(share.domain, style=f"bold {ACCENT}" if is_t else "bold")
        if is_t:
            domain.append("  ← Zieldomain", style=ACCENT_DIM)
        bar_style = ACCENT if is_t else AMBER
        fraction = share.citation_rate / scale if scale > 0 else 0.0
        table.add_row(
            str(share.rank),
            domain,
            f"{share.citation_count}x",
            f"{share.citation_rate:.0%}",
            _bar(fraction, 18, bar_style),
        )
    console.print(table)


def render_coverage(console: Console, report: CoverageReport) -> None:
    """Rendert die Query-Intent-Coverage (WOFUER zitiert?): Blind Spots je Fragetyp.

    Schwaechster Intent zuerst (wie ``compute_coverage`` sortiert). Ein Intent unter der
    Blind-Spot-Schwelle (``weakest_intents``) wird rot markiert. Liegen ``suggested_queries``
    vor (Query-Generator, LLM), werden die vorgeschlagenen Luecken-Fragen darunter gelistet.
    """
    console.print()
    console.rule(
        Text("WOFUER — Query-Intent-Coverage (Blind Spots)", style=f"bold {ACCENT}"),
        style=ACCENT_DIM,
        align="left",
    )
    weak = set(report.weakest_intents)
    table = Table(
        show_header=True,
        header_style=f"bold {GREY}",
        border_style="grey30",
        caption=(
            f"{report.n_probes} Probes · Gesamt-Zitationsrate {report.overall_citation_rate:.2f} · "
            f"{len(weak)} Blind Spot(s)"
        ),
        caption_style=GREY,
        expand=True,
    )
    table.add_column("", width=6)
    table.add_column("Fragetyp", ratio=2)
    table.add_column("Abdeckung", justify="right", width=10)
    table.add_column("Rate", justify="right", width=6)
    table.add_column("", width=16)
    for cov in report.intents:
        is_weak = cov.intent in weak
        marker = (
            Text("● LUECKE", style=f"bold {RED}")
            if is_weak
            else Text("● OK", style=f"bold {ACCENT}")
        )
        bar_style = RED if is_weak else ACCENT
        table.add_row(
            marker,
            Text(INTENT_LABELS[cov.intent], style="bold"),
            f"{cov.n_covered}/{cov.n_prompts}",
            f"{cov.mean_citation_rate:.2f}",
            _bar(cov.coverage_rate, 16, bar_style),
        )
    console.print(table)
    if report.suggested_queries:
        console.print(
            Text("Vorgeschlagene Luecken-Fragen (Query-Generator):", style=f"bold {ACCENT}")
        )
        for query in report.suggested_queries:
            line = Text()
            line.append(f"  + [{INTENT_LABELS[query.intent]}] ", style=ACCENT_DIM)
            line.append(query.text, style="bold")
            console.print(line)


def render_entity_graph(console: Console, report: EntityGraphReport) -> None:
    """Rendert den Entity-/Knowledge-Graph (WER — Entitaeten-Klarheit) + den JSON-LD-Fix.

    Zeigt die deklarierten Entitaeten (Marke + schema.org-Typen mit Deckung), die
    schwaechsten Seiten (Klarheits-Luecken, rot) und den empfohlenen kanonischen
    Organization-JSON-LD-Block — die konkrete semantische Fix-Vorlage.
    """
    console.print()
    console.rule(
        Text("WER — Entitaeten-Klarheit (Knowledge-Graph)", style=f"bold {ACCENT}"),
        style=ACCENT_DIM,
        align="left",
    )
    weak = set(report.weakest_pages)
    table = Table(
        show_header=True,
        header_style=f"bold {GREY}",
        border_style="grey30",
        caption=(
            f"Marke {report.brand_name} · mittlere Klarheit {report.mean_clarity:.2f} · "
            f"{len(weak)} Seite(n) mit Luecken"
        ),
        caption_style=GREY,
        expand=True,
    )
    table.add_column("Entitaet", ratio=2)
    table.add_column("schema.org", width=16)
    table.add_column("Seiten", justify="right", width=7)
    table.add_column("Deckung", width=18)
    for node in report.entities:
        marker = "★ " if node.kind.value == "brand" else ""
        bar_style = ACCENT if node.coverage_rate > 0 else RED
        table.add_row(
            Text(f"{marker}{node.name}", style="bold"),
            Text(node.schema_type, style=ACCENT_DIM),
            str(node.pages_declaring),
            _bar(node.coverage_rate, 14, bar_style),
        )
    console.print(table)
    if weak:
        gaps = ", ".join(_short_url(url) for url in report.weakest_pages[:6])
        console.print(Text(f"Klarheits-Luecken: {gaps}", style=RED))
    if report.brand_same_as:
        console.print(
            Text(
                f"sameAs-Autoritaets-Quellen (Entity-Extractor): {len(report.brand_same_as)}",
                style=f"bold {ACCENT}",
            )
        )
        for url in report.brand_same_as:
            line = Text()
            line.append("  → ", style=ACCENT_DIM)
            line.append(url, style="bold")
            console.print(line)
    jsonld = Panel(
        Text(report.recommended_jsonld, style=GREY),
        title=Text(" Empfohlener JSON-LD (Organization) ", style=f"bold black on {ACCENT}"),
        title_align="left",
        border_style=ACCENT_DIM,
        padding=(1, 2),
    )
    console.print(jsonld)


def render_patterns(console: Console, report: PatternReport) -> None:
    """Rendert Akt 2 (WARUM ranken die Top-Seiten?): die geminten Templates."""
    console.print()
    console.rule(
        Text("WARUM — Muster der Top-Seiten (Pattern-Miner)", style=f"bold {ACCENT}"),
        style=ACCENT_DIM,
        align="left",
    )
    table = Table(
        show_header=True,
        header_style=f"bold {GREY}",
        border_style="grey30",
        expand=True,
    )
    table.add_column("ID", width=4)
    table.add_column("Muster", ratio=3)
    table.add_column("Konfidenz", width=22)
    for tmpl in report.templates:
        levers = " · ".join(LEVER_LABELS[lever] for lever in tmpl.levers)
        cell = Text()
        cell.append(tmpl.title, style="bold")
        cell.append(f"\n{PYRAMID_LABELS[tmpl.pyramid_level]}  ·  {levers}", style=ACCENT_DIM)
        cell.append(f"\n{tmpl.summary}", style=GREY)
        confidence = Text()
        confidence.append_text(_bar(tmpl.confidence, 14, ACCENT))
        confidence.append(f" {tmpl.confidence:.2f}", style="bold")
        table.add_row(Text(tmpl.template_id, style=f"bold {AMBER}"), cell, confidence)
    console.print(table)


def render_findings(console: Console, report: AuditReport) -> None:
    """Rendert Akt 3 (WAS tun?): die priorisierten Audit-Findings."""
    console.print()
    console.rule(
        Text("WAS TUN — Priorisierte Findings (GEO-Auditor)", style=f"bold {ACCENT}"),
        style=ACCENT_DIM,
        align="left",
    )
    table = Table(
        show_header=True,
        header_style=f"bold {GREY}",
        border_style="grey30",
        caption="Priorisierung: untere Pyramide-Ebene zuerst, dann Schweregrad",
        caption_style=GREY,
        expand=True,
    )
    table.add_column("#", justify="right", width=3)
    table.add_column("Schwere", width=10)
    table.add_column("Seite · Hebel", ratio=2)
    table.add_column("Fix · Beleg", ratio=3)
    for position, finding in enumerate(report.findings, start=1):
        page = Text()
        page.append(_short_url(finding.target_url), style="bold")
        page.append(
            f"\n{PYRAMID_LABELS[finding.pyramid_level]} · {LEVER_LABELS[finding.lever]}",
            style=ACCENT_DIM,
        )
        fix = Text()
        fix.append(finding.recommendation)
        fix.append(f"\nBeleg: {finding.evidence}", style=GREY)
        table.add_row(str(position), _severity_badge(finding.severity), page, fix)
    console.print(table)


def render_fixplan(console: Console, plan: FixPlan) -> None:
    """Rendert Akt 4 (FIX): die konkreten Patches des Fix-Agents."""
    console.print()
    console.rule(
        Text("FIX — Vorgeschlagene Patches (Fix-Agent)", style=f"bold {ACCENT}"),
        style=ACCENT_DIM,
        align="left",
    )
    table = Table(
        show_header=True,
        header_style=f"bold {GREY}",
        border_style="grey30",
        caption=f"{len(plan.proposals)} Patches · Prompt {plan.prompt_version} · vor Freigabe",
        caption_style=GREY,
        expand=True,
    )
    table.add_column("#", justify="right", width=3)
    table.add_column("Typ", width=13)
    table.add_column("Seite · Hebel", ratio=2)
    table.add_column("Vorschlag · Beleg", ratio=3)
    table.add_column("Konfidenz", width=18)
    for position, patch in enumerate(plan.proposals, start=1):
        page = Text()
        page.append(_short_url(patch.target_url), style="bold")
        page.append(
            f"\n{PYRAMID_LABELS[patch.pyramid_level]} · {LEVER_LABELS[patch.lever]}",
            style=ACCENT_DIM,
        )
        proposal = Text()
        snippet = patch.proposed_content.replace("\n", " ")
        proposal.append(snippet[:140] + ("…" if len(snippet) > 140 else ""))
        proposal.append(f"\n{patch.rationale}", style=GREY)
        confidence = Text()
        confidence.append_text(_bar(patch.confidence, 12, ACCENT))
        confidence.append(f" {patch.confidence:.2f}", style="bold")
        table.add_row(
            str(position),
            Text(f" {_CHANGE_TYPE_LABELS[patch.change_type]} ", style=f"bold black on {AMBER}"),
            page,
            proposal,
            confidence,
        )
    console.print(table)


def render_hitl(console: Console, plan: FixPlan, decisions: dict[str, ApprovalDecision]) -> None:
    """Rendert Akt 5 (FREIGABE): die Human-in-the-Loop-Entscheidung je Patch."""
    console.print()
    console.rule(
        Text("FREIGABE — Human-in-the-Loop", style=f"bold {ACCENT}"),
        style=ACCENT_DIM,
        align="left",
    )
    table = Table(
        show_header=True,
        header_style=f"bold {GREY}",
        border_style="grey30",
        caption="Kein Deploy ohne Freigabe — der Mensch entscheidet (Projektregeln §6)",
        caption_style=GREY,
        expand=True,
    )
    table.add_column("Entscheidung", width=14)
    table.add_column("Seite · Patch", ratio=3)
    table.add_column("Reviewer", ratio=1)
    for patch in plan.proposals:
        decision = decisions.get(patch.patch_id)
        approved = decision is not None and decision.approved
        badge = (
            Text(" ✓ FREIGABE ", style=f"bold black on {ACCENT}")
            if approved
            else Text(" ✗ ABLEHNUNG ", style="bold white on #a8392c")
        )
        page = Text()
        page.append(_short_url(patch.target_url), style="bold")
        page.append(f"  {patch.patch_id}", style=GREY)
        reviewer = Text(decision.reviewer if decision is not None else "—", style=GREY)
        table.add_row(badge, page, reviewer)
    console.print(table)


def render_deploy(console: Console, result: DeployResult) -> None:
    """Rendert Akt 6 (DEPLOY): das Ergebnis des sicheren Dry-Run-Deploys."""
    console.print()
    console.rule(
        Text("DEPLOY — Anwenden (Dry-Run)", style=f"bold {ACCENT}"),
        style=ACCENT_DIM,
        align="left",
    )
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=GREY, justify="right")
    grid.add_column()
    grid.add_row("Publisher", Text(result.publisher, style="bold"))
    safety = (
        Text(" DRY-RUN · KEINE EXTERNEN WRITES ", style=f"bold black on {ACCENT}")
        if result.dry_run
        else Text(" LIVE ", style="bold white on #a8392c")
    )
    grid.add_row("Sicherheit", safety)
    status_badge = Text(f" {result.status.value.upper()} ", style=_DEPLOY_STYLES[result.status])
    grid.add_row("Status", status_badge)
    grid.add_row(
        "Patches",
        Text(
            f"{len(result.applied_patch_ids)} angewandt · "
            f"{len(result.skipped_patch_ids)} uebersprungen",
            style="bold",
        ),
    )
    if result.artifact_path is not None:
        grid.add_row("Artefakt", Text(result.artifact_path, style=GREY))
    if result.detail:
        grid.add_row("", Text(result.detail, style=GREY))
    console.print(
        Panel(
            grid,
            title=Text(" Deploy (Dry-Run) ", style=f"bold black on {ACCENT}"),
            title_align="left",
            border_style=ACCENT_DIM,
            padding=(1, 2),
        )
    )


def render_effect(console: Console, report: EffectReport) -> None:
    """Rendert Akt 7 (EFFEKT): die Vorher/Nachher-Re-Probe und die gelernten Hypothesen."""
    console.print()
    console.rule(
        Text("EFFEKT — Re-Probe & Gedaechtnis (Sprint 4)", style=f"bold {ACCENT}"),
        style=ACCENT_DIM,
        align="left",
    )
    if not report.hypotheses:
        console.print(
            Text(
                "Keine freigegebenen Patches → kein Effekt gemessen (HITL bleibt hart).",
                style=GREY,
            )
        )
        return
    n_significant = sum(1 for h in report.hypotheses if h.significant)
    table = Table(
        show_header=True,
        header_style=f"bold {GREY}",
        border_style="grey30",
        caption=(
            f"{report.n_improved}/{len(report.hypotheses)} signifikant verbessert · "
            f"{n_significant} statistisch belastbar (95%-KI ohne Null) · "
            f"mittleres Δ {report.mean_delta:+.2f} · in das Gedaechtnis geschrieben"
        ),
        caption_style=GREY,
        expand=True,
    )
    table.add_column("Seite · Hebel", ratio=3)
    table.add_column("Vorher", justify="right", width=6)
    table.add_column("Nachher", justify="right", width=7)
    table.add_column("Δ Rate", width=14)
    table.add_column("95%-KI", justify="center", width=15)
    table.add_column("Richtung", width=13)
    table.add_column("Konfidenz", width=13)
    for hyp in report.hypotheses:
        page = Text()
        page.append(_short_url(hyp.target_url), style="bold")
        page.append(
            f"\n{PYRAMID_LABELS[hyp.pyramid_level]} · {LEVER_LABELS[hyp.lever]}",
            style=ACCENT_DIM,
        )
        delta_bar = Text()
        delta_style = ACCENT if hyp.delta >= 0 else RED
        delta_bar.append_text(_bar(abs(hyp.delta), 8, delta_style))
        delta_bar.append(f" {hyp.delta:+.2f}", style="bold")
        if hyp.ci_low is not None and hyp.ci_high is not None:
            ci_style = ACCENT if hyp.significant else GREY
            ci_cell = Text(f"[{hyp.ci_low:+.2f}, {hyp.ci_high:+.2f}]", style=ci_style)
        else:
            ci_cell = Text("—", style=GREY)
        label, style = _DIRECTION_BADGES[hyp.direction]
        confidence = Text()
        confidence.append_text(_bar(hyp.confidence, 8, ACCENT))
        confidence.append(f" {hyp.confidence:.2f}", style="bold")
        table.add_row(
            page,
            f"{hyp.before_citation_rate:.2f}",
            f"{hyp.after_citation_rate:.2f}",
            delta_bar,
            ci_cell,
            Text(f" {label} ", style=style),
            confidence,
        )
    console.print(table)


def render_trend(console: Console, report: TrendReport) -> None:
    """Rendert das Monitoring (WANN — Zitations-Trend): Zeitreihe je Lauf + Drift-Alert.

    Zeigt die Gesamt-Zitationsrate pro Lauf (aeltester -> neuester) und den Vergleich des
    letzten mit dem vorherigen Lauf. Ein Rueckgang ueber der Schwelle wird als roter Alert
    hervorgehoben — das Fruehwarnsignal.
    """
    console.print()
    console.rule(
        Text("WANN — Zitations-Trend (Monitoring)", style=f"bold {ACCENT}"),
        style=ACCENT_DIM,
        align="left",
    )
    if not report.points:
        console.print(
            Text(f"Keine abgeschlossenen Laeufe fuer {report.target_domain}.", style=GREY)
        )
        return
    scale = max((point.overall_citation_rate for point in report.points), default=0.0)
    table = Table(
        show_header=True,
        header_style=f"bold {GREY}",
        border_style="grey30",
        caption=(
            f"{report.n_runs} Laeufe · Mittel {report.mean_rate:.2f} · "
            f"letzter Lauf {TREND_DIRECTION_LABELS[report.direction]} ({report.delta:+.2f})"
        ),
        caption_style=GREY,
        expand=True,
    )
    table.add_column("#", justify="right", width=3)
    table.add_column("Lauf", ratio=1, no_wrap=True)
    table.add_column("Rate", justify="right", width=6)
    table.add_column("", width=20)
    for position, point in enumerate(report.points, start=1):
        fraction = point.overall_citation_rate / scale if scale > 0 else 0.0
        table.add_row(
            str(position),
            Text(point.run_id, style="bold"),
            f"{point.overall_citation_rate:.2f}",
            _bar(fraction, 20, ACCENT),
        )
    console.print(table)
    if report.alert:
        console.print(
            Text(
                f" ⚠ DRIFT-ALERT — Zitier-Anteil um {abs(report.delta):.2f} gesunken "
                f"(Schwelle {report.drift_threshold:.2f}) ",
                style="bold white on #a8392c",
            )
        )
    elif report.direction is TrendDirection.IMPROVED:
        console.print(
            Text(f"▲ Zitier-Anteil gestiegen (+{report.delta:.2f})", style=f"bold {ACCENT}")
        )


def render_summary(
    console: Console,
    *,
    snapshot: CostSnapshot,
    fingerprint: str,
    seed: int,
    duration_s: float,
) -> None:
    """Rendert das Abschluss-Panel: Kosten, Dauer und den Determinismus-Fingerprint."""
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=GREY, justify="right")
    grid.add_column()
    grid.add_row(
        "Kosten/Lauf",
        Text(
            f"{snapshot.probes} Probes · {snapshot.total_tokens} Tokens · "
            f"${snapshot.total_usd:.4f}",
            style="bold",
        ),
    )
    grid.add_row("Dauer", Text(f"{duration_s:.1f} s", style="bold"))
    fingerprint_text = Text()
    fingerprint_text.append(fingerprint, style=f"bold {ACCENT}")
    fingerprint_text.append(f"   (Seed {seed})", style=GREY)
    grid.add_row("Report-Fingerprint", fingerprint_text)
    grid.add_row(
        "",
        Text("Gleicher Seed ⇒ gleicher Fingerprint — der Lauf ist reproduzierbar.", style=GREY),
    )
    console.print()
    console.print(
        Panel(
            grid,
            title=Text(" Lauf abgeschlossen ", style=f"bold black on {ACCENT}"),
            title_align="left",
            border_style=ACCENT_DIM,
            padding=(1, 2),
        )
    )


def render_error(console: Console, *, title: str, message: str) -> None:
    """Rendert einen Fehlerabbruch als rotes Panel (statt nacktem Text)."""
    console.print(
        Panel(
            Text(message),
            title=Text(f" {title} ", style="bold white on #a8392c"),
            title_align="left",
            border_style=RED,
            padding=(1, 2),
        )
    )
