"""Indexing-Adapter (Live-Loop): reichen URLs nach echtem Deploy bei Such-Indexen ein.

Alle Adapter erfuellen ``IndexingPort`` (Vertrag: ``submit`` wirft nach erfolgreicher
Konstruktion NIE — HTTP-/Transportfehler werden als Status im ``IndexSubmissionResult``
abgebildet). ``MockIndexingAdapter`` ist der deterministische Offline-Default (kein I/O,
immer ``SKIPPED``/Dry-Run); ``IndexNowAdapter`` spricht live api.indexnow.org an
(Bing/Yandex/Naver/Seznam) und ist nur mit Key + explizitem Opt-in erreichbar.
"""

from __future__ import annotations
