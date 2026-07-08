"""Unit: ChromaMemoryAdapter gegen echtes chromadb mit einem injizierten Fake-Embedder.

chromadb ist transitiv (via crewai) vorhanden; sentence-transformers/torch NICHT. Durch das
Injizieren einer deterministischen Fake-Embedding-Funktion wird die store/retrieve-/Filter-Logik
des Adapters real geprueft, OHNE die schwere ``memory``-Extra-Abhaengigkeit (bleibt opt-in).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

chromadb = pytest.importorskip("chromadb")

# chromadb warnt beim Persistieren eigener (Test-)Embedding-Funktionen — hier bewusst ignoriert.
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

from geo_audit_loop.domain.effect import EffectDirection, EffectHypothesis  # noqa: E402
from geo_audit_loop.domain.fix import ChangeType  # noqa: E402
from geo_audit_loop.domain.geo import Lever, PyramidLevel  # noqa: E402
from geo_audit_loop.domain.memory import MemoryQuery  # noqa: E402
from geo_audit_loop.memory.chroma import ChromaMemoryAdapter  # noqa: E402

FIXED = datetime(2026, 1, 1, 12, 0, 0)


class _FakeEmbedder:
    """Deterministische 8-dim-Embeddings aus dem Text — kein Modell, kein Netz.

    Implementiert die chromadb-1.1-Embedding-Schnittstelle (``__call__`` +
    ``embed_documents``/``embed_query``), damit der Adapter real gegen chromadb laeuft.
    """

    @staticmethod
    def is_legacy() -> bool:
        return False

    def __call__(self, input: list[str]) -> list[list[float]]:  # chromadb-Signatur (Documents)
        vectors: list[list[float]] = []
        for text in input:
            vec = [0.0] * 8
            for i, char in enumerate(text):
                vec[i % 8] += (ord(char) % 17) / 17.0
            vectors.append(vec)
        return vectors

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self(input)

    @staticmethod
    def name() -> str:
        return "fake-embedder"


def _hyp(
    *,
    hid: str,
    domain: str = "it-sicherheit.de",
    lever: Lever = Lever.ANSWER_BLOCKS,
    delta: float = 0.6,
    confidence: float = 0.8,
) -> EffectHypothesis:
    return EffectHypothesis(
        hypothesis_id=hid,
        run_id="r0",
        target_domain=domain,
        target_url=f"https://www.{domain}/page",
        patch_id=f"px-{hid}",
        finding_id="f1",
        lever=lever,
        pyramid_level=PyramidLevel.EXTRACTABILITY,
        change_type=ChangeType.INSERT_BLOCK,
        before_citation_rate=0.0,
        after_citation_rate=round(delta, 6),
        before_n=240,
        after_n=240,
        delta=round(delta, 6),
        direction=EffectDirection.IMPROVED,
        confidence=confidence,
        suspected_cause="x",
        observed_at=FIXED,
    )


def _adapter(tmp_path: Path) -> ChromaMemoryAdapter:
    return ChromaMemoryAdapter(chroma_path=tmp_path / "chroma", embedding_function=_FakeEmbedder())


def test_store_and_retrieve_roundtrip(tmp_path: Path) -> None:
    mem = _adapter(tmp_path)
    hyp = _hyp(hid="h1")
    mem.store(hyp)
    got = mem.retrieve(MemoryQuery(target_domain="it-sicherheit.de"))
    assert [h.hypothesis_id for h in got] == ["h1"]
    assert got[0] == hyp


def test_domain_isolation(tmp_path: Path) -> None:
    mem = _adapter(tmp_path)
    mem.store(_hyp(hid="h1", domain="it-sicherheit.de"))
    mem.store(_hyp(hid="h2", domain="example.com"))
    got = mem.retrieve(MemoryQuery(target_domain="it-sicherheit.de"))
    assert [h.hypothesis_id for h in got] == ["h1"]  # example.com bleibt aussen vor


def test_lever_filter(tmp_path: Path) -> None:
    mem = _adapter(tmp_path)
    mem.store(_hyp(hid="h1", lever=Lever.ANSWER_BLOCKS))
    mem.store(_hyp(hid="h2", lever=Lever.MACHINE_READABLE))
    got = mem.retrieve(MemoryQuery(target_domain="it-sicherheit.de", lever=Lever.MACHINE_READABLE))
    assert [h.hypothesis_id for h in got] == ["h2"]


def test_store_is_idempotent(tmp_path: Path) -> None:
    mem = _adapter(tmp_path)
    mem.store(_hyp(hid="h1", confidence=0.5))
    mem.store(_hyp(hid="h1", confidence=0.9))  # gleiche id -> Upsert
    got = mem.retrieve(MemoryQuery(target_domain="it-sicherheit.de", top_k=5))
    assert len(got) == 1
    assert got[0].confidence == 0.9


def test_top_k_limits_results(tmp_path: Path) -> None:
    mem = _adapter(tmp_path)
    for i in range(5):
        mem.store(_hyp(hid=f"h{i}"))
    got = mem.retrieve(MemoryQuery(target_domain="it-sicherheit.de", top_k=2))
    assert len(got) == 2
