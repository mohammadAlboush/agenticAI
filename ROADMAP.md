# Roadmap — `geo-audit-loop`: von der Mess-Schleife zur GEO-Intelligence-Plattform

> 10 Sessions, die aus dem heutigen selbstlernenden Audit-Loop ein **vorführbares,
> kausal-rigoroses, kompetitives GEO-Intelligence-System** machen. Jede Session ist ein
> abgeschlossener, lauffähiger Sprint mit eigenem Contract, Eval-Slot und Demo — nichts
> davon verletzt die Projektregeln (CLAUDE.md): **Ports & Adapters**, **Pydantic-Contracts
> zwischen Agenten**, **HITL vor jedem Deploy**, **Budget-Cap**, **Determinismus/Repro**,
> **kein Agent ohne Eval**.

---

## Ausgangslage (heute abgeschlossen: Sprint 1–6)

Der Regelkreis ist geschlossen **und statistisch fundiert**:

- **Messen** — Multi-Proxy-Probing-Matrix über AI-Engines; Top/Flop mit **Wilson-95%-KI** je
  Seite und Sichtbarkeits-Band (Sprint 6).
- **Verstehen** — Pattern-Miner (Templates) + GEO-Auditor (priorisierte Findings), beide sehen
  jetzt das statistische Band.
- **Fixen** — Fix-Agent → HITL-Gate → (Dry-Run-)Deploy.
- **Lernen** — Effekt-Re-Probe mit **Newcombe-95%-KI**; nur **signifikante** Effekte verfeinern
  den nächsten Fix-Run (Sprint 5).

**Was fehlt, um „Leistung zu zeigen":** echte Breite (alle Engines), echte Tiefe (Wettbewerber,
Entitäten), echter Deploy (nicht nur Dry-Run), echte Kausalität (kontrollierte Experimente),
echter Dauerbetrieb (Monitoring) und ein echtes Produkt (Plattform). Genau das liefern die
10 Sessions.

---

## Leitplanken (gelten in **jeder** Session)

| Regel | Bedeutung für die Roadmap |
|---|---|
| **Ports & Adapters** | Neue Außenwelt (Engines, WordPress, Scheduler) kommt **nur** als Adapter hinter einem Port. Der Kern bleibt mockbar. |
| **Contracts zuerst** | Jede Session beginnt mit dem Pydantic-Contract + Port, dann Eval-Gerüst, dann Adapter, dann Agent, dann Orchestrierung. |
| **HITL bleibt hart** | Kein Schritt umgeht das Freigabe-Gate — auch der echte Deploy (Session 5) nicht. |
| **Determinismus** | Neue Domänen-Mathematik ist rein und gerundet (bit-reproduzierbar); Nicht-Determinismus (LLM/Netz) wird dokumentiert. |
| **Budget-Cap** | Jeder neue externe Aufruf zählt gegen das harte Run-Limit. |
| **Eval-Slot** | Kein neuer Agent ohne Golden-/Toleranz-Eval. |

---

## Die 10 Sessions

### Session 1 — Live Multi-Engine Citation Observatory
**Ziel:** Reales Live-Probing über die vollständige Palette der Antwort-Engines: ChatGPT (Search),
Claude (Web-Search-Tool), Google AI Overviews, Bing Copilot — zusätzlich zu Perplexity/Gemini.
**Warum (Leistung):** Zitier-Sichtbarkeit ist **engine-spezifisch**. Erst ein echter Cross-Engine-Blick
macht jede Aussage belastbar — und die Demo eindrucksvoll („so wirst du in 6 Engines zitiert").
**Was gebaut wird:** je Engine ein `EnginePort`-Adapter; Normalisierung der heterogenen Citation-Formate
auf das eine `Citation`-Modell; Erweiterung der `config/engines.py`-Registry; Rate-Limit-/Proxy-Handling;
Budget-Cap je Engine.
**Definition of Done:** je Adapter ein gemockter Unit-Test + ein opt-in Live-Test (default geskippt);
Citation-Normalisierung getestet; **kein Netz in CI**.
**Hängt an:** bestehende `EnginePort`, `ProxyPort`.

### Session 2 — Adaptive Sequential Sampling (kosten-smarte Messung)
**Ziel:** Statt fixer 240-Probe-Matrix **sequenziell** proben und stoppen, sobald das Wilson-KI einer
Seite eng genug ist (Ziel-Präzision) — mehr Probes dorthin, wo die Unsicherheit hoch ist.
**Warum (Leistung):** Nutzt direkt die Sprint-6-KIs als **Steuersignal**: gleiche statistische Präzision
bei einem Bruchteil der Kosten/Zeit. Das ist der Unterschied zwischen „Demo" und „skalierbar".
**Was gebaut wird:** `SamplingPolicy`-Contract (Ziel-Halbbreite, min/max Probes); sequenzielle Allokation
im Sampler; deterministische Reihenfolge; Budget-Cap-Integration.
**Definition of Done:** Unit-Tests für Konvergenz (KI erreicht Ziel-Breite), Determinismus und sauberen
Budget-Abbruch; Eval, dass die Ziel-Präzision reproduzierbar getroffen wird.
**Hängt an:** Sprint 6 (Wilson-KI), Sampler.

### Session 3 — Competitive Intelligence: Share of Voice
**Ziel:** Je Query messen, **welche Domains/Seiten** die Engines zitieren (nicht nur die eigene). Daraus
ein **Citation Share of Voice** je Wettbewerber; die Top-Seiten der Wettbewerber in den Pattern-Miner speisen.
**Warum (Leistung):** **Flaggschiff-Feature.** Man lernt am schnellsten von denen, die bereits gewinnen —
„diese 3 Wettbewerber holen 60 % der Zitate; das machen sie anders". Genau der Aha-Moment für eine Präsentation.
**Was gebaut wird:** `CompetitorProfile`/`ShareOfVoice`-Contracts; Konkurrenz-Extraktion aus den bereits
gesammelten Citations (keine neuen Probes nötig); Miner mint zusätzlich aus Wettbewerber-Exemplaren; Report + Render.
**Definition of Done:** deterministische Share-of-Voice-Aggregation (Unit-Test); Miner-Eval-Slot erweitert;
HITL/Budget unverändert.
**Hängt an:** Session 1 (mehr Engines = belastbarere Share-of-Voice), Pattern-Miner.

### Session 4 — Query Space Discovery & Coverage
**Ziel:** Die fixen 12 Prompts zu einem **entdeckten Query-Raum** erweitern (LLM-Query-Generierung +
Intent-Clustering); Abdeckung je Intent messen; Blind Spots aufzeigen.
**Warum (Leistung):** Beantwortet die strategische Frage „**wofür** bist du unsichtbar?" — nicht nur
„wie sichtbar bist du?". Deckt ganze Themen-/Intent-Lücken auf, die im 12-Prompt-Fenster verborgen bleiben.
**Was gebaut wird:** `QueryGenerator`-Agent (über `ReasoningPort`); Intent-Taxonomie-Contract;
Coverage-Report je Intent; versionierter Prompt + Eval-Slot.
**Definition of Done:** Query-Generator-Eval (Toleranz); deterministische Coverage-Aggregation getestet;
Budget-Cap für die Generierung.
**Hängt an:** Sampler, ReasoningPort.

### Session 5 — Echter Deploy hinter HITL: WordPress live
**Ziel:** Den WordPress-Stub zu einem **echten Publisher** machen — freigegebene Patches via REST-API an
eine Live-Seite anwenden, hinter dem harten HITL-Gate, mit **Security-Review** und **Rollback**.
**Warum (Leistung):** Schließt den Loop **wirklich**. Bisher endet er im Dry-Run; jetzt fließt der Weg
vom Vorschlag zur an einer realen Seite gemessenen Wirkung. Das ist der Sprung von „Analyse" zu „Wirkung".
**Was gebaut wird:** `WordPressPublisher`-Adapter (idempotentes Apply, Rollback-Fähigkeit, Audit-Trail);
Secrets über `.env`; verpflichtender Durchlauf der Security-Review; das HITL-Gate bleibt **unverändert hart**.
**Definition of Done:** Adapter gegen einen gemockten WP-Client getestet; Rollback getestet; Live nur
hinter explizitem Flag; Security-Review dokumentiert. **Projektregel §6 bleibt: kein Auto-Deploy.**
**Hängt an:** bestehender `PublisherPort`, HITL-Gate.

### Session 6 — Kausale Experimente: von Vorher/Nachher zu Difference-in-Differences
**Ziel:** Die Effekt-Messung von reinem Vorher/Nachher zu einem **kontrollierten Experiment** aufwerten:
Fix auf eine Treatment-Seite, gematchte Control-Seite ohne Fix; **Difference-in-Differences** mit der
Sprint-5-KI-Maschinerie; randomisierte (seed-basierte) Zuordnung.
**Warum (Leistung):** **Wissenschaftliches Kronjuwel.** Trennt den Fix-Effekt von Markt-/Zeit-Trends —
genau die kausale Rigorosität, die ein Master-Forschungsprojekt von einem Bastel-Tool unterscheidet.
**Was gebaut wird:** `Experiment`/`TreatmentArm`-Contracts; reiner, deterministischer DiD-Schätzer mit
KI; seed-basierte Randomisierung; Erweiterung des Effekt-Analysten.
**Definition of Done:** DiD-Schätzer gegen einen Referenzfall getestet; Determinismus; Eval-Slot;
Hypothesen tragen jetzt Experiment-Provenienz.
**Hängt an:** Sprint 5 (Effekt-KI), Session 5 (echter Deploy ermöglicht echte Treatments).

### Session 7 — Continuous Monitoring & Scheduled Runs
**Ziel:** Von Einzel-Läufen zu **kontinuierlichem Monitoring**: geplante Läufe (Cron), Zeitreihe des
Zitier-Anteils, **Drift-/Regressions-Alerts**, Trend-Dashboard.
**Warum (Leistung):** Macht aus einem Audit-Tool ein **Frühwarnsystem** — „deine NIS2-Seite hat diese
Woche signifikant Zitier-Anteil verloren". Wiederkehrender Nutzen statt Momentaufnahme.
**Was gebaut wird:** migrationssichere Zeitreihen-Persistenz (SQLite-Schema erweitern); Scheduler-Anbindung;
KI-basierte Alert-Regeln (signifikanter Rückgang = KI-Trennung über die Zeit); Dashboard-Trends-Ansicht.
**Definition of Done:** deterministische Trend-/Alert-Logik getestet; Schema-Migration getestet;
Idempotenz (keine Doppel-Läufe pro Fenster).
**Hängt an:** Sprint 6 (KI), Persistenz, Dashboard.

### Session 8 — Entity & Knowledge Graph Optimization
**Ziel:** Einen **Wissensgraphen** der Domain-Entitäten bauen; messen, wie AI-Engines sie auflösen
(Hebel *Entitäten-Klarheit*); strukturierte Daten generieren (JSON-LD, `sameAs`, Entity-Linking).
**Warum (Leistung):** Adressiert einen der 10 Hebel **in der Tiefe** statt oberflächlich — Entitäten sind,
*wie* AI-Engines eine Marke „verstehen". Das hebt die Fixes von Textblöcken auf semantische Infrastruktur.
**Was gebaut wird:** Entity-Extraktion (ReasoningPort); `EntityGraph`-Contract; Entitäten-Klarheit-Auditor
+ -Fixer; deterministischer JSON-LD-Generator.
**Definition of Done:** Entity-Extraktion-Eval; deterministische Graph-Serialisierung; Fixer-Eval-Slot.
**Hängt an:** GEO-Auditor, Fix-Agent.

### Session 9 — Portfolio & Cross-Domain Meta-Learning
**Ziel:** **Viele Domains** verwalten; eine Meta-Memory-Schicht, die **übertragbare Strategien** lernt
(„`add_schema` auf FAQ-Seiten hebt Zitation domänenübergreifend") — bei **striktem Erhalt der
Domain-Isolation** des eigentlichen Priors.
**Warum (Leistung):** Skaliert das Lernen: aus N Domains entsteht Strategiewissen, das keine Einzeldomain
hätte. Zeigt, dass der Lern-Loop nicht nur pro Domain, sondern als **System** lernt.
**Was gebaut wird:** `PortfolioManager`; Meta-Memory mit aggregierten, anonymisierten Meta-Hypothesen;
Transfer-Prior — wirkt nur als **schwächerer Default**, nie über den domäneneigenen Prior (Isolation gewahrt).
**Definition of Done:** Isolationstest bleibt grün (kein Leck zwischen Domains); Meta-Aggregation
deterministisch; Transfer-Prior-Eval; Meta-Prior ist im Code **und** Prompt nachvollziehbar (§8).
**Hängt an:** Sprint 5 (MemoryPort), Session 6 (belastbare Effekte als Meta-Grundlage).

### Session 10 — Executive Reporting, ROI & Web-Plattform
**Ziel:** Die volle **Web-Plattform**: Executive-Reports (Narrativ „warum zitiert / was tun /
prognostizierte Wirkung"), **ROI-Schätzung** (Zitier-Anteil → Traffic/Leads-Modell), Effekt- **und**
KI-Tabelle im Dashboard (schließt die S5/S6-Dashboard-Lücke), PDF-Export, Produktivierung (Auth, async).
**Warum (Leistung):** Macht aus dem Instrument ein **vorführbares Produkt** — hier wird die „Leistung"
für Betreuer/Stakeholder sichtbar und greifbar.
**Was gebaut wird:** Reporting-Engine (narrativ + Zahlen); Dashboard-Vervollständigung; ROI-Modell;
Async-Runner; einfache Auth.
**Definition of Done:** Report-Rendering getestet; Dashboard-Integration-Tests (auch die neuen KI-Felder);
ROI-Modell dokumentiert und deterministisch.
**Hängt an:** alle vorigen Sessions (die Plattform bündelt das Ergebnis).

---

## Leistungs-Höhepunkte (die „Wow"-Momente)

1. **Cross-Engine-Zitier-Radar** (S1): „So wirst du in 6 AI-Engines zitiert" — auf einen Blick.
2. **Share of Voice gegen Wettbewerber** (S3): „Diese 3 gewinnen 60 % der Zitate — und *das* tun sie anders."
3. **Echter Live-Fix mit gemessener Wirkung** (S5+S6): Vorschlag → Freigabe → Live-Deploy →
   **kontrolliertes Experiment** → belastbarer, kausaler Effekt.
4. **Frühwarnsystem** (S7): automatischer Alert bei signifikantem Zitier-Verlust.
5. **Selbstlernendes Portfolio** (S9): das System lernt Strategien, die einzeln nicht sichtbar wären.

---

## Ordnungs-Logik (warum diese Reihenfolge)

```
Breite & Effizienz   →   Intelligenz            →   Wirkung & Rigor        →   Betrieb & Produkt
S1 Engines               S3 Wettbewerber            S5 Live-Deploy             S7 Monitoring
S2 Adaptive Sampling     S4 Query-Coverage          S6 Kausale Experimente     S8 Entity-Graph
                                                                                S9 Portfolio-Meta
                                                                                S10 Plattform
```

- **Erst Breite/Effizienz (S1–S2):** belastbare, bezahlbare Messung ist das Fundament jeder Aussage.
- **Dann Intelligenz (S3–S4):** Wettbewerbs- und Query-Kontext machen die Analyse strategisch.
- **Dann Wirkung/Rigor (S5–S6):** echter Deploy + kontrollierte Experimente = beweisbare Wirkung.
- **Dann Betrieb/Produkt (S7–S10):** Dauerbetrieb, semantische Tiefe, Skalierung, vorführbare Plattform.

Jede Session ist einzeln lauffähig und demonstrierbar — die Roadmap liefert also in **jedem** Schritt
einen sichtbaren Fortschritt, nicht erst am Ende.
