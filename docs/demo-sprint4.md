# Sprint-4-Demo — Der geschlossene Lern-Loop (offline, deterministisch)

> Ziel der Demo: in **einem** Befehl den **geschlossenen Regelkreis** zeigen — messen (*was*),
> verstehen (*warum*), maßnehmen (*was tun*), fixen + freigeben + (Dry-Run-)deployen, dann den
> **Effekt re-proben** und als `EffectHypothesis` ins **Gedächtnis** schreiben. Ein **zweiter** Lauf
> beweist: das System **lernt** — es fixt nachweislich anders. Alles ohne Netz/Kosten, ohne je eine
> Live-Seite zu berühren.

## Voraussetzung

```bash
uv sync        # einmalig; venv + Abhängigkeiten (das schwere memory-Extra ist NICHT nötig)
```

## Der eine Befehl

```bash
uv run python -m geo_audit_loop --domain it-sicherheit.de --offline --learn --approve-all --seed 42 --pace 0.6
```

- `--learn` → Sprint-4-Lern-Loop (impliziert `--fix` und `--explain`): Gedächtnis-Abruf **vor** dem
  Fix, Effekt-Re-Probe **nach** dem Deploy.
- `--offline` → deterministische Mock-Engines **und** Mock-Reasoning **und** Mock-Gedächtnis (Seed 42).
- `--approve-all` → gibt in der nicht-interaktiven Demo alle Patches frei (sonst wird je Patch gefragt).
- `--pace 0.6` (optional) → kurze Lesepause zwischen den Abschnitten (Live/Video).

## Was passiert (7 Akte)

1. **WAS** — Sampler (Baseline-Probe-Matrix) + Crawler → Top/Flop-Sichtbarkeitsliste.
2. **WARUM** — der **Pattern-Miner** mint Best-Practice-`Template`s der Top-Seiten.
3. **WAS TUN** — der **GEO-Auditor** liefert priorisierte `AuditFinding`s der Flop-Seiten.
4. **GEDÄCHTNIS** — der Loop ruft passende frühere `EffectHypothesis` ab (im 1. Lauf noch leer).
5. **FIX** — der **gedächtnis-informierte Fix-Agent** macht je Finding einen `FixProposal`; erwiesen
   wirksame `(Hebel, ChangeType)` werden **höher priorisiert** (explizit in Code *und* Prompt v2).
6. **FREIGABE + DEPLOY (Dry-Run)** — HITL entscheidet je Patch; der Publisher meldet, was angewandt
   *würde* — Badge **„DRY-RUN · KEINE EXTERNEN WRITES"**. Ohne Freigabe passiert **nichts**.
7. **EFFEKT** — der Sampler **re-probet** dieselbe Matrix (`REPROBE`-Phase); der **Effekt-Analyst**
   vergleicht Vorher/Nachher je Zielseite, bildet je Patch eine `EffectHypothesis` (Delta, Confidence,
   Ursache) und **schreibt sie ins Gedächtnis**. Panel **EFFEKT** zeigt Vorher → Nachher, Δ und Richtung.

## Determinismus zeigen (Master-Kriterium)

Den Befehl (ohne `--pace`) **zweimal auf je frischer DB** ausführen → der **Report-Fingerprint ist
identisch**, obwohl die run-ID variiert. Der Fingerprint (`domain/fingerprint.py`) rechnet jetzt auch
den **Effekt-Report** mit ein (laufvariable Zeitstempel/IDs bleiben außen vor). Der Offline-Effekt ist
ein **deterministischer** Boost der gepatchten URLs im Mock-Engine — kein Zufall.

```bash
GEO_DB_PATH=$(mktemp -d)/a.db uv run python -m geo_audit_loop --domain it-sicherheit.de --offline --learn --approve-all --seed 42
GEO_DB_PATH=$(mktemp -d)/b.db uv run python -m geo_audit_loop --domain it-sicherheit.de --offline --learn --approve-all --seed 42
# beide Läufe → derselbe 12-stellige Fingerprint (z. B. 6446d32aacac)
```

## Lernen zeigen (der eigentliche Sprint-4-Beweis)

Zweimal auf **derselben** DB laufen lassen → Lauf 2 **liest** die Hypothesen von Lauf 1 aus dem
Gedächtnis, der Fix-Plan (Confidence/Reihenfolge) **ändert sich**, und der Fingerprint ist ein
**anderer** als der Frisch-Lauf:

```bash
DB=$(mktemp -d)/mem.db
GEO_DB_PATH=$DB uv run python -m geo_audit_loop --domain it-sicherheit.de --offline --learn --approve-all --seed 42
GEO_DB_PATH=$DB uv run python -m geo_audit_loop --domain it-sicherheit.de --offline --learn --approve-all --seed 42 --run-id run-2
# Lauf 2 zeigt „Gedächtnis — X Hypothesen" und einen abweichenden Fingerprint -> es hat gelernt.
```

Der Mechanismus ist **explizit** (Projektregeln §8): `apply_memory_prior` (`domain/memory.py`)
verschiebt die Patch-Confidence anhand erwiesener Effekte; `prioritize_proposals` ordnet den Plan
dadurch messbar um. Zusätzlich rendert `fix_agent.v2.md` die Hypothesen für den Live-LLM.

## Sicherheit zeigen (HITL bleibt hart)

- Deploy ist und bleibt **Dry-Run** — der echte Remote-Publisher ist blockiert (`stub_remote.py`).
- Lehnt man alle Patches ab (`RejectAllGate`), wird **nichts** angewandt, **nichts** re-geprobt und
  **nichts** gelernt (ehrlicher Null-Effekt). Belegt durch
  `tests/integration/test_sprint4_flow.py::test_sprint4_hitl_reject_yields_no_effect`.

## Dashboard-Variante (optional)

```bash
uv run python -m geo_audit_loop --serve          # http://127.0.0.1:8042
```

Im „Neuer Lauf"-Formular **Lernen** wählen → das Dashboard startet denselben Lauf (`--learn
--approve-all`); `/api/state` und `/api/results` liefern den Effekt (Vorher/Nachher, Δ, Hypothesen).

## Ehrlichkeits-Hinweis (Forschungsredlichkeit)

Der Offline-Effekt ist eine **deterministische Simulation** (Boost der gepatchten URLs), damit der
geschlossene Loop reproduzierbar und demonstrierbar ist. Ein **Live**-Deploy ist bewusst Dry-Run —
eine Live-Re-Probe würde daher ehrlich ≈ 0 messen. Der Determinismus-Beweis (Fingerprint) gilt
offline; Live-Läufe (Gemini-Zitate, echtes Reasoning, Chroma-Retrieval) sind naturgemäß nicht
bit-reproduzierbar und als solche dokumentiert.

## Begleitend

- Tests/Evals: `uv run pytest` — u. a.
  `tests/integration/test_sprint4_flow.py` (Komplettlauf + HITL + Reproduzierbarkeit),
  `tests/integration/test_memory_influence.py` (das System **lernt**),
  `tests/eval/test_eval_effect_golden.py` (toleranzbasierter Effekt-Eval),
  `tests/unit/test_mock_memory.py` · `tests/unit/test_effect_analyst.py` (Gedächtnis + Effekt-Analyst).
