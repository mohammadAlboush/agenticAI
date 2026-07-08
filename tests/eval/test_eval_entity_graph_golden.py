"""Eval-Harness: Golden-Regression des deterministischen Entity-/Knowledge-Graphs (Session 8).

Der Entity-Graph ist eine reine, seed-stabile Domaenenfunktion (kein LLM/RNG). Dieser Test
pinnt seine Offline-Ausgabe bei Seed 42 **bit-genau** gegen die Golden-Datei: Entity-Knoten
(Marke + deklarierte schema.org-Typen mit Deckung), Klarheit je Seite, Blind-Spot-Liste und
den empfohlenen JSON-LD-Block. Anders als die toleranzbasierten LLM-Evals ist hier exakte
Gleichheit die Erwartung; eine bewusste Aenderung aktualisiert das Golden im selben Commit.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from geo_audit_loop.config.settings import Settings
from geo_audit_loop.orchestration.factory import assemble_run
from geo_audit_loop.prompts.loader import load_probe_set

FIXED = datetime(2026, 1, 1, 12, 0, 0)
GOLDEN = Path(__file__).parent / "golden" / "entity_graph_it_sicherheit_seed42.json"


def test_entity_graph_matches_golden(tmp_path: Path) -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    settings = Settings(
        db_path=tmp_path / "geo.db",
        max_probes=1000,
        n_proxy_ips=5,
        top_n=10,
        run_seed=golden["seed"],
    )
    version, prompts = load_probe_set(golden["prompt_set_version"])
    assembly = assemble_run(
        settings,
        domain=golden["domain"],
        offline=True,
        run_id="eval-entity",
        now=FIXED,
        prompts=prompts,
        prompt_version=version,
    )
    assembly.pipeline.run()
    graph = assembly.pipeline.entity_graph
    assembly.storage.close()

    assert graph is not None
    dump = graph.model_dump(mode="json", exclude={"run_id", "generated_at"})
    assert dump == golden["entity_graph"]  # bit-genau, deterministisch
