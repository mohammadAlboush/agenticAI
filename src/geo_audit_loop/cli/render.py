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
from geo_audit_loop.domain.findings import TopFlopEntry, TopFlopReport
from geo_audit_loop.domain.geo import LEVER_LABELS, PYRAMID_LABELS
from geo_audit_loop.domain.templates import PatternReport
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
) -> None:
    """Rendert das Kopf-Panel mit Run-Metadaten."""
    mode = (
        Text(" OFFLINE · DETERMINISTISCH ", style=f"bold black on {ACCENT}")
        if offline
        else Text(" LIVE ", style=f"bold black on {AMBER}")
    )
    title = Text()
    title.append("geo-audit-loop", style=f"bold {ACCENT}")
    title.append(" · Sprint 2 — Learning", style="bold")
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
    table = Table(
        show_header=True,
        header_style=f"bold {GREY}",
        border_style="grey30",
        caption=f"{report.n_probes} Probes · {report.n_pages} Seiten der Domain",
        caption_style=GREY,
        expand=True,
    )
    table.add_column("", width=6)
    table.add_column("#", justify="right", width=3)
    table.add_column("URL", ratio=2, no_wrap=True)
    table.add_column("Zitationen", justify="right", width=10)
    table.add_column("Rate", justify="right", width=6)
    table.add_column("", width=16)

    scale = max(
        (entry.citation_rate for entry in (*report.top, *report.flop)),
        default=0.0,
    )

    def _row(marker: Text, entry: TopFlopEntry, bar_style: str) -> None:
        fraction = entry.citation_rate / scale if scale > 0 else 0.0
        table.add_row(
            marker,
            str(entry.position),
            Text(_short_url(entry.url), style="bold"),
            f"{entry.citation_count}x",
            f"{entry.citation_rate:.2f}",
            _bar(fraction, 16, bar_style),
        )

    for entry in report.top:
        _row(Text("▲ TOP", style=f"bold {ACCENT}"), entry, ACCENT)
    if report.top and report.flop:
        table.add_section()
    for entry in report.flop:
        _row(Text("▼ FLOP", style=f"bold {RED}"), entry, RED)
    console.print(table)


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
