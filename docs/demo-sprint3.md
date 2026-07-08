# Sprint-3-Demo — Live-Ablauf (offline, deterministisch)

> Ziel der Demo: in **einem** Befehl den geschlossenen Loop zeigen — von der Messung (*was*)
> über das Verständnis (*warum*) und die Maßnahme (*was tun*) bis zur **Umsetzung**: konkrete
> Patches (FIX), menschliche **Freigabe** (HITL) und sicherer **Dry-Run-Deploy** — reproduzierbar,
> ohne Netz/Kosten und **ohne je eine Live-Seite zu berühren**.

## Voraussetzung

```bash
uv sync        # einmalig; venv + Abhängigkeiten
```

## Der eine Befehl

```bash
uv run python -m geo_audit_loop --domain it-sicherheit.de --offline --explain --fix --apply --approve-all --seed 42 --pace 0.6
```

- `--offline` → deterministische Mock-Engines **und** Mock-Reasoning (Seed 42).
- `--explain` → Sprint-2-Lern-Loop (Pattern-Miner + GEO-Auditor).
- `--fix` / `--apply` → Sprint-3-Fix-/Deploy-Loop (impliziert `--explain`).
- `--approve-all` → gibt in der nicht-interaktiven Demo alle Patches frei (sonst wird je Patch gefragt).
- `--pace 0.6` (optional) → kurze Lesepause zwischen den Abschnitten (Live/Video).

## Was passiert (6 Akte)

1. **WAS** — Sampler (Probe-Matrix) + Crawler erzeugen die Top/Flop-Sichtbarkeitsliste.
2. **WARUM** — der **Pattern-Miner** mint Best-Practice-`Template`s der Top-Seiten.
3. **WAS TUN** — der **GEO-Auditor** liefert priorisierte `AuditFinding`s der Flop-Seiten.
4. **FIX** — der **Fix-Agent** macht aus jedem Finding einen konkreten `FixProposal` (Patch):
   Antwortblock, FAQ-/Autor-Schema, Vergleichstabelle … — mit Beleg, Hebel und Konfidenz.
5. **FREIGABE** — das **Human-in-the-Loop-Gate** entscheidet je Patch (hier: alle freigegeben).
   Ohne Freigabe wird **nichts** angewandt (Projektregeln §6).
6. **DEPLOY (Dry-Run)** — der **Publisher** meldet, welche freigegebenen Patches angewandt
   *würden* — Badge **„DRY-RUN · KEINE EXTERNEN WRITES"**. Die Zieldomain bleibt unberührt.

## Erwartete Ausgabe (rich-Terminal-UI, gekürzt; Seed 42 → exakt reproduzierbar)

- **Header**: Modus-Badge `OFFLINE · DETERMINISTISCH`, Stufe `Sprint 3 — Fix & Deploy`, Seed, run-ID.
- **WAS / WARUM / WAS TUN** wie in Sprint 2 (Top/Flop, Templates, priorisierte Findings).
- **FIX** — Tabelle der 6 Patches mit Typ-Badge (`Block +`, `Schema +`), Seite·Hebel,
  Vorschlag·Beleg und Konfidenz-Balken.
- **FREIGABE** — je Patch `✓ FREIGABE` + Reviewer; Fußzeile „Kein Deploy ohne Freigabe".
- **DEPLOY (Dry-Run)** — Panel:

```
   Publisher  mock
  Sicherheit   DRY-RUN · KEINE EXTERNEN WRITES
      Status   DRY_RUN
     Patches  6 angewandt · 0 uebersprungen
```

- **Abschluss-Panel**: Kosten/Lauf · Report-Fingerprint (Seed 42).

## Determinismus zeigen (Master-Kriterium)

Den Befehl (ohne `--pace`) **zweimal** ausführen → der **Report-Fingerprint ist identisch**,
obwohl die run-ID pro Lauf variiert. Der Fingerprint (`domain/fingerprint.py`) rechnet jetzt
auch den **Fix-Plan** mit ein (`ApprovalDecision`/`DeployResult` bleiben außen vor — sie tragen
laufvariable Zeitstempel). Der ganze Loop ist trotz LLM-Schritten bit-genau reproduzierbar
(Mock-Reasoning, Seed 42, deterministische `patch_id`).

```bash
uv run python -m geo_audit_loop --domain it-sicherheit.de --offline --explain --fix --approve-all --seed 42
uv run python -m geo_audit_loop --domain it-sicherheit.de --offline --explain --fix --approve-all --seed 42
# beide Läufe → derselbe 12-stellige Fingerprint
```

## Sicherheit zeigen (HITL-Gate, optional)

Das Gate ist nicht nur Konvention, sondern in Code erzwungen und getestet
(`tests/integration/test_hitl_gate.py`):

- `apply_patches` **ohne** vorherige Freigabe → `DeployBlocked`, kein `DeployResult`.
- Lehnt man alle Patches ab (`RejectAllGate`), wird **nichts** angewandt und der
  `FilesystemPublisher` schreibt **null** Dateien.

## Sprechzettel (3 Sätze)

1. „Sprint 2 sagt mir priorisiert, *was* an `/passwort-manager-vergleich` fehlt — aber tut es nicht."
2. „Der Fix-Agent macht daraus einen konkreten Patch — z. B. eine Vergleichstabelle mit Product-Schema —
   und legt ihn dem Menschen zur Freigabe vor; **ohne Freigabe kein Deploy**."
3. „Der Deploy läuft als sicherer Dry-Run: Er zeigt, was angewandt *würde*, berührt aber nie die
   Live-Seite — und der Fingerprint beweist, dass der ganze Loop reproduzierbar ist."

## Dashboard-Variante (optional)

```bash
uv run python -m geo_audit_loop --serve          # http://127.0.0.1:8042
```

Im „Neuer Lauf"-Formular **Fix & Deploy** anhaken → das Dashboard startet denselben Lauf
(`--fix --approve-all`) und zeigt **Schritt 6: Patches + Deploy (Dry-Run)** read-only.

## Begleitend

- Demo-Video: `docs/sprint3-demo.mp4` (Bildschirmaufnahme des Doppellaufs, wie Sprint 2).
- Folien: `docs/sprint3-praesentation.html`.
- Tests/Evals: `uv run pytest` — u. a. `tests/integration/test_hitl_gate.py` (hartes Gate),
  `tests/integration/test_sprint3_flow.py` (Komplettlauf + Reproduzierbarkeit),
  `tests/eval/test_eval_fix_agent_golden.py` (toleranzbasierter Fix-Agent-Eval).
```
