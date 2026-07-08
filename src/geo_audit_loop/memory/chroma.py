"""Gedaechtnis-Adapter: Chroma + bge-m3 Embeddings (CLAUDE.md §2, opt-in/live).

Erfuellt ``MemoryPort`` mit **semantischem** Abruf ueber einen persistenten Chroma-Store und
bge-m3-Embeddings. Die schweren Importe (``chromadb``, ``sentence-transformers``/``torch``)
sind **lazy** und liegen im optionalen Extra ``memory`` — der deterministische Offline-/CI-/
Eval-Pfad (``MockMemoryAdapter``) laedt sie nie (spiegelt das Mock/Live-Muster der Engines).

SQLite bleibt das System of Record (der volle Hypothesen-JSON liegt in den Chroma-Metadaten
als ``payload`` und wird beim Abruf rekonstruiert); Chroma ist der Retrieval-Index. Der
semantische Abruf ist store-/modellabhaengig und daher **nicht** bit-reproduzierbar
(dokumentierte Nicht-Determinismus-Quelle, Projektregeln §7) — deshalb ausschliesslich live.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from geo_audit_loop.config import constants as c
from geo_audit_loop.domain.effect import EffectHypothesis
from geo_audit_loop.domain.errors import StorageError
from geo_audit_loop.domain.memory import MemoryQuery

_COLLECTION = "effect_hypotheses"


def _embed_text_for_hypothesis(hyp: EffectHypothesis) -> str:
    """Deterministischer Embedding-Text einer Hypothese (strukturierte Merkmale)."""
    return (
        f"{hyp.lever.value} {hyp.pyramid_level.value} {hyp.change_type.value} "
        f"{hyp.target_domain} {hyp.direction.value}"
    )


def _embed_text_for_query(query: MemoryQuery) -> str:
    """Embedding-Text eines Abfragekontexts (analog zum Hypothesen-Text, ohne Richtung)."""
    parts = [
        query.lever.value if query.lever is not None else "",
        query.pyramid_level.value if query.pyramid_level is not None else "",
        query.change_type.value if query.change_type is not None else "",
        query.target_domain,
    ]
    return " ".join(p for p in parts if p)


def _where(query: MemoryQuery) -> dict[str, Any]:
    """Baut den Chroma-Metadaten-Filter (Pflicht: Domain; optional: Hebel)."""
    conditions: list[dict[str, Any]] = [{"target_domain": query.target_domain}]
    if query.lever is not None:
        conditions.append({"lever": query.lever.value})
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


class ChromaMemoryAdapter:
    """Semantisches Gedaechtnis ueber Chroma + bge-m3 (erfuellt ``MemoryPort``; opt-in/live)."""

    def __init__(
        self,
        *,
        chroma_path: Path,
        embedding_model: str = c.DEFAULT_EMBEDDING_MODEL,
        embedding_function: Any = None,  # Chroma-EmbeddingFunction (kein Typ-Stub) — CLAUDE.md §4
        collection_name: str = _COLLECTION,
    ) -> None:
        try:
            import chromadb  # lazy: nur im Live-Pfad, nie in CI/Offline

            ef = embedding_function if embedding_function is not None else _bge_m3(embedding_model)
            client = chromadb.PersistentClient(path=str(chroma_path))
            # ``self._collection`` ist ``Any`` — chromadb liefert keine Typ-Stubs (mypy-Override).
            self._collection = client.get_or_create_collection(
                name=collection_name,
                embedding_function=ef,
                metadata={"hnsw:space": "cosine"},
            )
        except ImportError as exc:
            raise StorageError(
                "ChromaMemoryAdapter braucht das optionale Extra 'memory' "
                "(pip install 'geo-audit-loop[memory]')"
            ) from exc

    def store(self, hypothesis: EffectHypothesis) -> None:
        """Persistiert eine Hypothese idempotent im Chroma-Store (Upsert ``hypothesis_id``)."""
        self._collection.upsert(
            ids=[hypothesis.hypothesis_id],
            documents=[_embed_text_for_hypothesis(hypothesis)],
            metadatas=[
                {
                    "target_domain": hypothesis.target_domain,
                    "lever": hypothesis.lever.value,
                    "pyramid_level": hypothesis.pyramid_level.value,
                    "change_type": hypothesis.change_type.value,
                    "payload": hypothesis.model_dump_json(),
                }
            ],
        )

    def retrieve(self, context: MemoryQuery) -> list[EffectHypothesis]:
        """Liefert die semantisch naechsten, domaingefilterten Hypothesen (``top_k``)."""
        result = self._collection.query(
            query_texts=[_embed_text_for_query(context)],
            where=_where(context),
            n_results=context.top_k,
            include=["metadatas"],
        )
        metadatas = result.get("metadatas") or [[]]
        rows = metadatas[0] if metadatas else []
        return [EffectHypothesis.model_validate_json(str(md["payload"])) for md in rows]


def _bge_m3(model_name: str) -> Any:  # Chroma-EmbeddingFunction (kein Typ-Stub) — CLAUDE.md §4
    """Lazy-Fabrik der bge-m3-Embedding-Funktion (zieht sentence-transformers/torch)."""
    from chromadb.utils import embedding_functions

    return embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name)
