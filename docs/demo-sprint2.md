# Sprint-2-Demo — Live-Ablauf (offline, deterministisch)

> Ziel der Demo: in **einem** Befehl zeigen, wie der Loop von der Messung (*was* wird zitiert)
> zum Verständnis (*warum*) und zur Maßnahme (*was tun*) kommt — reproduzierbar, ohne Netz/Kosten.

## Voraussetzung

```bash
uv sync        # einmalig; venv + Abhängigkeiten
```

## Der eine Befehl

```bash
uv run python -m geo_audit_loop --domain it-sicherheit.de --offline --explain --top-n 3 --log-level WARNING
```

- `--offline` → deterministische Mock-Engines **und** Mock-Reasoning (Seed 42).
- `--explain` → hängt den Sprint-2-Lern-Loop an (Pattern-Miner + GEO-Auditor).
- `--log-level WARNING` → unterdrückt die JSON-Logzeilen für eine saubere Demo-Ausgabe.
- `--pace 3` (optional) → 3 s Lesepause zwischen den Report-Abschnitten (Live-Präsentation/Video).

## Was passiert (3 Akte)

1. **WAS** — Sampler (240 Probes) + Crawler erzeugen die Top/Flop-Sichtbarkeitsliste.
2. **WARUM** — der **Pattern-Miner** mint aus den Top-Seiten 3 Best-Practice-`Template`s
   (verankert in den 10 Hebeln + Citation-Pyramide).
3. **WAS TUN** — der **GEO-Auditor** prüft die Flop-Seiten gegen die Templates und liefert
   6 nach Pyramide **priorisierte** `AuditFinding`s.

## Erwartete Ausgabe (rich-Terminal-UI, gekürzt; Seed 42 → exakt reproduzierbar)

Die CLI rendert eine strukturierte Terminal-UI (`cli/render.py`):

- **Header-Panel** mit Domain, Modus-Badge (`OFFLINE · DETERMINISTISCH`), Seed, run-ID, Prompt-Version.
- **Live-Schrittanzeige** der vier Flow-Schritte mit Häkchen, Kennzahl und Dauer:

```
✓ Probe-Matrix sampeln (Engines x Prompts x IPs)  240 Probes · 2.0 s
✓ Inventar crawlen + Top/Flop-Report              8 Seiten · 0.0 s
✓ Pattern-Miner — Muster der Top-Seiten           3 Templates · 0.0 s
✓ GEO-Auditor — Flop-Seiten pruefen               6 Findings · 0.0 s
```

- **WAS** — Top/Flop-Tabelle mit Zitations-Balken:
  TOP `/nis2-richtlinie` (71x · 0.30), `/ransomware-schutz` (42x), `/zero-trust-architektur` (39x);
  FLOP `/security-awareness-training` (7x), `/passwort-manager-vergleich` (17x), `/firewall-grundlagen` (19x).
- **WARUM** — 3 Muster mit Konfidenz-Balken: `t1` Extrahierbarer Antwortblock + FAQ-Schema (0.82),
  `t2` Autor-Entität + Faktendichte (0.76), `t3` Schritt-für-Schritt-Struktur/HowTo (0.71).
- **WAS TUN** — 6 priorisierte Findings mit farbigen Severity-Badges (HIGH/MEDIUM/LOW),
  Hebel, Fix und Beleg (untere Pyramide-Ebene zuerst, dann Schweregrad).
- **Abschluss-Panel**:

```
Kosten/Lauf          240 Probes · 39800 Tokens · $0.3115
Report-Fingerprint   0ab26644ea8d   (Seed 42)
```

## Determinismus zeigen (Master-Kriterium)

Den Befehl **zweimal** ausführen → der **Report-Fingerprint ist identisch** (`0ab26644ea8d`),
obwohl die run-ID pro Lauf variiert. Der Fingerprint (`domain/fingerprint.py`) ist der
SHA-256 über das kanonische JSON aller drei Reports **ohne** die laufvariablen Felder
`run_id`/`generated_at` — der Lern-Loop ist trotz LLM-Schritten bit-genau reproduzierbar
(Mock-Reasoning, Seed 42).

## Sprechzettel (3 Sätze)

1. „Sprint 1 sagt mir, dass `/passwort-manager-vergleich` selten zitiert wird — aber nicht warum."
2. „Der Pattern-Miner zeigt: Top-Seiten haben FAQ-Schema und einen extrahierbaren Antwortblock."
3. „Der GEO-Auditor sagt mir priorisiert, was genau zu tun ist — und Sprint 3 setzt es um."

## Optional: echtes Claude-Reasoning (nicht für die Live-Demo nötig)

```bash
# .env mit ANTHROPIC_API_KEY, dann:
GEO_LIVE_ENGINES=claude uv run python -m geo_audit_loop --domain it-sicherheit.de --explain
```

## Begleitend

- Demo-Video: `docs/sprint2-demo.mp4` (Bildschirmaufnahme des echten Doppellaufs, 1080p).
- Folien: `docs/sprint2-praesentation.html`.
- Tests/Evals: `uv run pytest` (toleranzbasierte Eval-Slots für beide Agenten;
  `tests/unit/test_cli_render.py` + `tests/unit/test_fingerprint.py` decken die neue CLI-Schicht ab).
