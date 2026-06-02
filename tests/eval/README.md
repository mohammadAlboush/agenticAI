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
