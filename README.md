# geo-audit-loop

Selbstlernendes agentisches **GEO/SEO-Audit-System**: ein geschlossener Regelkreis, der misst,
wie eine Website in Such- und AI-Engines **zitiert** wird, Schwachstellen gegen Best-Practice-
Templates auditiert, Fixes vorschlägt (Human-in-the-Loop), deployt und den Effekt re-probet.

Master-Modulprojekt · Agentic AI · Westfälische Hochschule · Master Informatik.

> **Status:** Sprint 4 (LERN-LOOP) abgeschlossen — der Regelkreis ist **geschlossen**: nach dem
> (Dry-Run-)Deploy misst das System den Effekt per Re-Probe, bildet daraus strukturierte
> `EffectHypothesis`-Objekte, schreibt sie ins `MemoryPort`-Gedächtnis und lässt sie den **nächsten**
> Fix-Run messbar verfeinern. `mypy --strict` · `ruff` · alle Tests grün, offline bit-genau
> reproduzierbar (der Effekt fließt in den Fingerprint).

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

> Demo: `docs/demo-sprint2.md` · Folien: `docs/sprint2-praesentation.html`.

---

## Sprint 3 — Summary

**Ziel:** Den Loop schließen — aus den priorisierten Findings nicht nur sagen, *was* zu tun ist,
sondern es **umsetzen**: konkrete Patches vorschlagen, nach **menschlicher Freigabe** anwenden.

**Gebaut:**
- **Fix-Agent:** macht aus jedem `AuditFinding` einen konkreten `FixProposal` (= Patch) — fertiger
  Antwortblock, FAQ-/Autor-/Product-Schema (JSON-LD), Vergleichstabelle … — mit Beleg, Hebel,
  Konfidenz und Herkunft (`finding_id` → Template). Über denselben `ReasoningPort` wie Sprint 2
  (Mock offline-deterministisch · SAIA/Claude live).
- **Human-in-the-Loop-Gate:** ein `ApprovalGate` entscheidet je Patch (`AutoApproveGate` für die
  Demo, interaktiver Gate in der CLI, `RejectAllGate` für Tests). **Hart erzwungen:** `apply_patches`
  ohne Freigabe wirft `DeployBlocked` — aus einem `FixPlan` wird **nie** direkt ein `DeployResult`.
- **Publisher-Port + Adapter:** `MockPublisher` (Default, reiner Dry-Run), `FilesystemPublisher`
  (schreibt Patch-Artefakte nach `runs/<run_id>/patches/` — **lokal**, nie die Live-Domain),
  `WordPress`/`GitHub`-Stubs hinter demselben Port (opt-in, in Sprint 3 blockiert). Nicht
  freigegebene Patches landen **immer** in `skipped_patch_ids`.
- **Contracts & Disziplin:** `FixProposal`/`FixPlan`/`ApprovalDecision`/`DeployResult` (+ Enums);
  deterministische `patch_id`; versionierter Prompt `fix_agent.v1.md`; toleranzbasierter Eval-Slot;
  `Sprint3Flow` orchestriert sample → … → propose → approve → deploy; Fingerprint rechnet den
  Fix-Plan mit ein (bit-genau reproduzierbar, Seed 42).

**Das System kann jetzt:** in **einem** Lauf messen, verstehen, priorisieren **und** den Fix
formulieren, freigeben und (Dry-Run) anwenden — offline deterministisch, ohne je eine Live-Seite zu
berühren (Projektregeln §6: kein Auto-Deploy ohne HITL).

> Demo: `docs/demo-sprint3.md` · Folien: `docs/sprint3-praesentation.html`.

---

## Sprint 4 — Summary

**Ziel:** Den Regelkreis **schließen** — nicht nur fixen, sondern den **Effekt messen** und daraus
**lernen**, sodass jeder Lauf die nächsten besser macht (Projektregeln §8).

**Gebaut:**
- **Effekt-Re-Probe:** Nach dem Dry-Run-Deploy misst der Sampler denselben Matrix-Schnitt erneut
  (`ProbePhase.REPROBE`, kollisionsfrei neben der Baseline unter **einer** `run_id`). Offline sorgt
  ein **deterministischer** Boost der gepatchten URLs im Mock-Engine für einen reproduzierbaren
  Vorher/Nachher-Lift; live wird die Realität gemessen (unter Dry-Run ehrlich ≈ 0).
- **`EffectHypothesis` (Contract §3.2):** je angewandtem Patch strukturiert — Vorher-/Nachher-Rate,
  Delta, **deterministische** Confidence (`|Δ|·n/(n+k)`), vermutete Ursache als `(Hebel, ChangeType)`,
  Provenienz zum Patch/Finding. Der **Effekt-Analyst** ist deterministisch (reine Domänen-Mathematik,
  kein LLM) → bleibt bit-reproduzierbar.
- **`MemoryPort` (genau `store`/`retrieve`, §8):** `MockMemoryAdapter` (Default, SQLite, deterministisch)
  **und** `ChromaMemoryAdapter` (bge-m3, opt-in Extra `memory`). Domain-isoliert (Lernen leckt nicht
  zwischen Domains).
- **Der Lern-Hebel — explizit in Code UND Prompt (§8):** vor dem Fix ruft der Loop passende
  Hypothesen ab; sie fließen (a) in `fix_agent.v2.md` (Live-LLM) **und** (b) deterministisch über
  `apply_memory_prior` in die Patch-Confidence → `prioritize_proposals` ordnet den Plan messbar um.
  Kein implizites „das LLM wird's schon nutzen".
- **Sicherheit unverändert:** Deploy bleibt Dry-Run; das HITL-Gate bleibt hart (ohne Freigabe kein
  Re-Probe, kein Lernen). Der Effekt fließt in den Report-Fingerprint (offline bit-genau).

**Das System kann jetzt:** in **einem** Lauf messen, verstehen, priorisieren, fixen, freigeben,
(Dry-Run-)deployen, den **Effekt re-proben** und als Hypothese ins Gedächtnis schreiben — und beim
**nächsten** Lauf nachweislich anders (besser) fixen. Der Regelkreis ist geschlossen.

**Bewusst offen (später):** echter WordPress/GitHub-Live-Deploy hinter dem bestehenden Port
(Credentials + Sicherheits-Review); reichere semantische Retrieval-Strategien im Chroma-Adapter.

> Demo: `docs/demo-sprint4.md`.

---

## Architektur

Hexagonal (Ports & Adapters). Der Kern (`domain` + `ports`) kennt keine konkrete Außenwelt.

```
src/geo_audit_loop/
  config/         Settings, Engine-Registry, Konstanten, Budget-/Preis-Tabelle
  domain/         reine Pydantic-Contracts + Domänenlogik (kein I/O) — inkl. effect/memory
  ports/          abstrakte Protocols (EnginePort, ProxyPort, CrawlPort, StoragePort, MemoryPort)
  adapters/       konkrete I/O-Implementierungen (engines, proxy, crawl, publisher, storage)
  agents/         Sampler, Crawler, Pattern-Miner, GEO-Auditor, Fix-Agent, Effekt-Analyst
  memory/         Gedächtnis hinter MemoryPort: MockMemoryAdapter (SQLite) + ChromaMemoryAdapter (bge-m3)
  orchestration/  CrewAI-Flow am Rand, verdrahtet den geschlossenen Loop (Sprint 1–4)
  prompts/        versionierte Probe-Sets + Agenten-Prompts (fix_agent.v2 = gedächtnis-informiert)
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

# Sprint-3-Fix-/Deploy-Loop: zusätzlich FIX (Patches) + FREIGABE (HITL) + DEPLOY (Dry-Run):
uv run python -m geo_audit_loop --domain it-sicherheit.de --offline --explain --fix --apply --approve-all --top-n 3

# Sprint-4-Lern-Loop: zusätzlich RE-PROBE (Effekt) + GEDÄCHTNIS — schließt den Regelkreis:
uv run python -m geo_audit_loop --domain it-sicherheit.de --offline --learn --approve-all --top-n 3
# Zweiter Lauf auf derselben DB nutzt das Gedächtnis des ersten -> der Fix-Plan ändert sich (Lernen).

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

## Steuerzentrale (Web-Dashboard)

Läufe **starten, stoppen, verwalten und live beobachten** — „Neuer Lauf"-Formular (Domain,
Offline/Live, Engine-/Reasoning-Auswahl je nach hinterlegten Keys, Top-N, Seed, Proxy-IPs),
Lauf-Verlauf mit Ansehen/Löschen, Probe-Matrix mit klickbaren Zellen (Antwort & Quellen),
Inventar, Top/Flop, Templates, Findings, Fingerprint:

```bash
uv run python -m geo_audit_loop --serve            # http://127.0.0.1:8042
```

Ein gestarteter Lauf läuft als eigener Prozess (exakt der CLI-Code-Pfad, vorab vergebene
`--run-id`); das Dashboard beobachtet ihn über die SQLite. Bindung nur an `127.0.0.1`.

## Echte Engines (kostenlos)

- **Reasoning (Pattern-Miner/GEO-Auditor): SAIA/KISSKI** — Hochschul-LLM-Dienst, OpenAI-kompatibel,
  kostenlos. `SAIA_API_KEY` in `.env`, dann `GEO_REASONING_PROVIDER=saia` (oder im Dashboard wählen).
- **Zitations-Messung: Gemini mit Google-Search-Grounding** — einziger echter Gratis-Weg zu
  Quellen-URLs (500 Anfragen/Tag frei, Stand 06/2026). Kostenlosen Key von
  [aistudio.google.com/apikey](https://aistudio.google.com/apikey) als `GOOGLE_API_KEY` in `.env`,
  dann `GEO_LIVE_ENGINES=gemini` (Free-Tier-Tipp: `GEO_N_PROXY_IPS=1` ⇒ 12 Anfragen/Lauf).
  Hinweis: SAIA-Modelle haben keine Websuche und liefern daher keine echten Quellen —
  deshalb die Aufteilung SAIA=Reasoning, Gemini=Zitate. Perplexity bleibt als bezahlte
  Live-Engine opt-in; Live-Läufe sind naturgemäß nicht bit-reproduzierbar (Fingerprint-Beweis
  gilt offline).
- **Zitations-Messung: Claude & ChatGPT mit Websuche (opt-in, bezahlt)** — hinter demselben
  `EnginePort` messen jetzt auch **Claude** (Anthropic Messages API + `web_search`-Server-Tool,
  `ANTHROPIC_API_KEY`) und **ChatGPT** (OpenAI Responses API + `web_search`, `OPENAI_API_KEY`),
  welche AI-Engine die Zieldomain zitiert. Aktivieren via `GEO_LIVE_ENGINES=claude,chatgpt` (oder
  gemischt mit `gemini`/`perplexity`). Nicht markierte Engines und der gesamte Offline-Pfad bleiben
  gemockt und bit-reproduzierbar. Die heterogenen Zitationsformate werden auf **ein** `Citation`-Modell
  normalisiert (Ports & Adapters, §3.1) — eine fünfte Engine ergänzt man ohne Kern-Änderung.
- **Crawl im Live-Modus:** Standardmäßig nutzen auch Live-Läufe das schnelle, deterministische
  Sample-Inventar der Domain (der echte advertools-Crawl ist langsam und kann in den
  5-Minuten-Timeout laufen). Für einen echten Crawl der Zieldomain: `--live-crawl` ergänzen.

## Eval

`tests/eval/` enthält den Eval-Harness. Sprint 1 pinnt die Top/Flop-Rangfolge der deterministischen
Pipeline gegen ein Golden-Dataset; nicht-deterministische Agenten (ab Sprint 2) docken
toleranzbasiert an. Details: `tests/eval/README.md`.

## Reproduzierbarkeit & Persistenz

Jeder Lauf bekommt eine `run_id`, einen `config_hash` (Fingerprint der Run-Konfiguration) und einen
Seed; Runs, Probes, Seiten-Inventar und Report werden in SQLite (`GEO_DB_PATH`) persistiert. Probes
sind idempotent (UNIQUE `run_id/prompt/engine/proxy`), ein abgebrochener Lauf wird beim Neustart
fortgesetzt statt doppelt zu proben (Checkpointing).
