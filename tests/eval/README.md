# Eval-Harness

Regressionsschutz fuer Agenten gegen Golden-Datasets (Projektregeln §5.3:
**kein Agent ohne mindestens einen Eval-Eintrag**).

## Sprint 1 (deterministisch)

Sampler und Inventory-Crawler sind deterministisch. Der Eval-Eintrag
`test_eval_topflop_golden.py` pinnt deshalb die **Top/Flop-Rangfolge** der
Offline-Pipeline bei festem Seed gegen `golden/topflop_it_sicherheit_seed42.json`.
Aenderungen an Mock-, Aggregations- oder Scoring-Logik werden so als Regression
sichtbar. Wird eine Aenderung bewusst vorgenommen, aktualisiert man die Golden-Datei
im selben Commit.

## Sprint 2+ (nicht-deterministisch)

Pattern-Miner und GEO-Auditor nutzen ein LLM. Ihre Evals docken an dieselbe Struktur
an, vergleichen aber **toleranzbasiert** (z. B. erwartete Template-Merkmale, Hebel-
Bezug, Pyramide-Ebene statt exakter Stringgleichheit). Prompt-Aenderungen werden
gegen diese Evals regressionsgetestet (Projektregeln §5.3).

## Sprint 4 (Effekt / Lern-Loop, deterministisch)

Der Effekt-Analyst ist deterministisch (reine Domaenen-Mathematik, kein LLM).
`test_eval_effect_golden.py` pinnt toleranzbasiert die Vorher/Nachher-Re-Probe gegen
`golden/effect_seed42.json`: Anzahl gebildeter Hypothesen in `[min,max]`, jede Hypothese
an einem tatsaechlich angewandten Patch verankert, nicht-negatives Delta (Offline-Boost)
und Confidence in `[0,1]`. Dass das Gedaechtnis den **naechsten** Fix-Run messbar
veraendert (das eigentliche „Lernen"), sichern zusaetzlich die Integrationstests
`tests/integration/test_memory_influence.py`.

## Session 3 (Competitive Share of Voice, deterministisch)

Der Share-of-Voice ist reine Domaenen-Mathematik ueber die Baseline-Citations (kein LLM).
`test_eval_share_of_voice_golden.py` pinnt toleranzbasiert die Wettbewerbslandschaft gegen
`golden/share_of_voice_seed42.json`: Anzahl zitierter Domains in `[min,max]`, **genau eine**
Zeile ist die Zieldomain, die Rangfolge faellt (totaler Ordnungsschluessel), alle Shares in
`[0,1]`, und die Wettbewerber-Seiten sind Nicht-Ziel-Seiten. Ein Golden-Unit-Test genuegt
(kein Agenten-Eval-Slot noetig, da deterministisch).
