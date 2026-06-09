# geo-audit-loop

Selbstlernendes agentisches **GEO/SEO-Audit-System**: ein geschlossener Regelkreis, der misst,
wie eine Website in Such- und AI-Engines **zitiert** wird, Schwachstellen gegen Best-Practice-
Templates auditiert, Fixes vorschlägt (Human-in-the-Loop), deployt und den Effekt re-probet.

Master-Modulprojekt · Agentic AI · Westfälische Hochschule · Master Informatik.

> **Status:** Sprint 2 (LEARNING) abgeschlossen — Pattern-Miner & GEO-Auditor über einem neuen
> `ReasoningPort` (Claude/Mock), toleranzbasierte Evals. `mypy --strict` · `ruff` · alle Tests grün.

---

## Sprint 1 — Summary

**Ziel:** Das Fundament des geschlossenen GEO/SEO-Audit-Loops bauen — die **Mess- und
Inventarschicht** — sauber, getestet und reproduzierbar.

**Gebaut:**
- **Hexagonale Architektur** (Ports & Adapters): der Kern (`domain` + `ports`) ist frei von
  jeder Außenwelt; Adapter sind im Test mockbar.
- **SERP & Citation Sampler:** Multi-Proxy-Probing-Matrix — 4 Engines × 12 Prompts × 5 Proxy-IPs
  = **240 Probes/Run**; der Median über die IPs eliminiert Personalisierungs-Bias. Die vier
  Engine-Citation-Formate werden auf **ein** normalisiertes `Citation`-Modell abgebildet.
- **Inventory-Crawler:** advertools im Subprozess (isolierter Reactor) + Schema-/On-Page-Inventar;
  Join mit den Sampler-Werten → **Top/Flop-Sichtbarkeitsliste**.
- **Persistenz & Sicherheit:** SQLite mit Idempotenz/Checkpointing (fortsetzbare Runs), harter
  **Budget-Cap**, Retry/Backoff, strukturiertes JSON-Logging mit `run_id`, `config_hash`/Seed
  für Reproduzierbarkeit.
- **Orchestrierung & CLI:** CrewAI-`Flow` am Rand über einer framework-freien Pipeline; CLI
  erzeugt die reproduzierbare Demo.

**Das System kann jetzt:** für eine Domain (`it-sicherheit.de`) **neutral messen**, welche Seiten
in AI-Engines zitiert werden, und daraus eine **Top/Flop-Liste** erzeugen — offline deterministisch
(Mock-Engines) oder live über **Perplexity**.

**Neu seit Sprint 0 (Pitch):** **alles.** Sprint 0 war reine Pitch-/Architektur-Konzeption;
Sprint 1 ist die erste lauffähige Implementierung — die gesamte Codebasis, Test- und Eval-Gerüst.

**Offene Punkte / nächster Schritt:** Sprint 2 (Learning) ist unten beschrieben. Danach: Fix-Agent
+ Human-in-the-Loop + Deploy (Sprint 3) und Re-Probe + Memory (Sprint 4).

---

## Sprint 2 — Summary

**Ziel:** Die Mess-Schicht lernfähig machen — aus der Top/Flop-Liste ableiten, **warum** Top-Seiten
zitiert werden und **was** den Flop-Seiten fehlt.

**Gebaut:**
- **ReasoningPort:** LLM-Schließen sauber getrennt vom SERP-`EnginePort`. Adapter:
  `MockReasoningAdapter` (offline, deterministisch) & `ClaudeReasoningAdapter` (live, opt-in) —
  dasselbe Mock-/Live-Muster wie bei den Engines.
- **Pattern-Miner:** mint aus den Top-Seiten wiederverwendbare `Template`s, verankert in den
  10 GEO-Hebeln und der Citation-Pyramide (Skill `geo-strategy`).
- **GEO-Auditor:** prüft Flop-Seiten gegen die Templates → nach Pyramide **priorisierte**
  `AuditFinding`s (Beleg, Hebel, Ebene, Schweregrad, Empfehlung).
- **Contracts & Disziplin:** `Template` / `AuditFinding` + GEO-Vokabular (`Lever`, `PyramidLevel`);
  versionierte Prompts (`pattern_miner.v1.md`, `geo_auditor.v1.md`); **toleranzbasierte Eval-Slots**
  je Agent; `Sprint2Flow` orchestriert sample → report → mine → audit.

**Das System kann jetzt:** in **einem** Lauf messen, *warum* Top-Seiten ranken und *was* an den
Flop-Seiten zu tun ist — offline deterministisch (Seed 42) oder mit Live-Claude. Ohne neue
Abhängigkeit (`anthropic` war bereits gepinnt).

**Bewusst offen (Fast-Follow / Sprint 3–4):** Live-Adapter ChatGPT & Gemini; `MemoryPort` +
Chroma/`bge-m3`; Fix-Agent + HITL + Deploy; Re-Probe + `EffectHypothesis`.

> Demo: `docs/demo-sprint2.md` · Folien: `docs/sprint2-praesentation.html`.

---

## Architektur

Hexagonal (Ports & Adapters). Der Kern (`domain` + `ports`) kennt keine konkrete Außenwelt.

```
src/geo_audit_loop/
  config/         Settings, Engine-Registry, Konstanten, Budget-/Preis-Tabelle
  domain/         reine Pydantic-Contracts + Domänenlogik (kein I/O)
  ports/          abstrakte Protocols (EnginePort, ProxyPort, CrawlPort, StoragePort)
  adapters/       konkrete I/O-Implementierungen (engines, proxy, crawl, storage)
  agents/         Sampler, Inventory-Crawler (deterministische Services)
  orchestration/  CrewAI-Flow am Rand, verdrahtet die Pipeline
  prompts/        versionierte Probe-Sets
  observability/  JSON-Logging (run_id), Cost-/Budget-Tracking, Retry
```

## Setup

Voraussetzung: [`uv`](https://docs.astral.sh/uv/). Python 3.12 wird von uv isoliert verwaltet.

```bash
uv sync                       # venv + Abhängigkeiten installieren
cp .env.example .env          # Secrets eintragen (nur für Live-Modus nötig)
```

## Entwicklung

```bash
uv run ruff check src tests   # Lint
uv run mypy                   # Typen (strict)
uv run pytest                 # Tests (alle Ports gemockt, kein Netz)
```

## Sprint-1-Demo

```bash
# Offline-Demo (Mock-Engines) — reproduzierbare Top/Flop-Liste für it-sicherheit.de:
uv run python -m geo_audit_loop --domain it-sicherheit.de --offline --top-n 3

# Sprint-2-Lern-Loop: zusätzlich WARUM (Templates) + WAS TUN (priorisierte Findings):
uv run python -m geo_audit_loop --domain it-sicherheit.de --offline --explain --top-n 3

# Opt-in Live-Probing (nur Perplexity, budget-gedeckelt; braucht .env + Proxies):
uv run python -m geo_audit_loop --domain it-sicherheit.de --live
```

Beispiel-Ausgabe (Offline, 240 Probes über 4 Engines × 12 Prompts × 5 IPs):

```
=== GEO-Sichtbarkeit: it-sicherheit.de (run 9bd9b4a1e867) ===
Probes: 240 | Seiten: 8

TOP (am häufigsten zitiert):
   1.  71x  rate=0.30  https://www.it-sicherheit.de/nis2-richtlinie
   2.  42x  rate=0.17  https://www.it-sicherheit.de/ransomware-schutz
   3.  39x  rate=0.16  https://www.it-sicherheit.de/zero-trust-architektur

FLOP (selten/nie zitiert):
   1.   7x  rate=0.03  https://www.it-sicherheit.de/security-awareness-training
   2.  17x  rate=0.07  https://www.it-sicherheit.de/passwort-manager-vergleich
   3.  19x  rate=0.08  https://www.it-sicherheit.de/firewall-grundlagen
```

> Offline nutzt deterministische Mock-Engines (Seed-gesteuert) — gleicher Seed liefert
> denselben Report. Im Live-Modus wird ausschließlich **Perplexity** real abgefragt;
> die übrigen Engines bleiben in Sprint 1 gemockt.

## Eval

`tests/eval/` enthält den Eval-Harness. Sprint 1 pinnt die Top/Flop-Rangfolge der deterministischen
Pipeline gegen ein Golden-Dataset; nicht-deterministische Agenten (ab Sprint 2) docken
toleranzbasiert an. Details: `tests/eval/README.md`.

## Reproduzierbarkeit & Persistenz

Jeder Lauf bekommt eine `run_id`, einen `config_hash` (Fingerprint der Run-Konfiguration) und einen
Seed; Runs, Probes, Seiten-Inventar und Report werden in SQLite (`GEO_DB_PATH`) persistiert. Probes
sind idempotent (UNIQUE `run_id/prompt/engine/proxy`), ein abgebrochener Lauf wird beim Neustart
fortgesetzt statt doppelt zu proben (Checkpointing).
