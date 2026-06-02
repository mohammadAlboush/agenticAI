"""Proxy-Adapter: Webshare-Liste (``ip:port:user:pass``) als seed-stabiler Pool.

Implementiert ``ProxyPort``. Die Rotation ist deterministisch: bei Konstruktion wird
der Pool mit einem lokalen ``random.Random(seed)`` einmalig permutiert (kein globaler
RNG), danach liefert ``get(index)`` reproduzierbar ``pool[index % size]``.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from pathlib import Path

from geo_audit_loop.domain.errors import ProxyError

_PARTS_PER_LINE = 4


def parse_webshare_file(path: Path) -> list[str]:
    """Liest eine Webshare-Datei und baut authentifizierte Proxy-URLs.

    Format je Zeile: ``ip:port:user:pass`` -> ``http://user:pass@ip:port``.
    Leere Zeilen werden ignoriert; fehlerhafte Zeilen werfen ``ProxyError``.
    """
    if not path.exists():
        raise ProxyError(f"Proxy-Datei nicht gefunden: {path}")
    urls: list[str] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split(":")
        if len(parts) != _PARTS_PER_LINE:
            raise ProxyError(f"Zeile {lineno}: erwartet 'ip:port:user:pass', erhalten {line!r}")
        ip, port, user, password = parts
        urls.append(f"http://{user}:{password}@{ip}:{port}")
    return urls


class WebshareProxyPool:
    """Seed-stabiler, index-basierter Proxy-Pool (erfuellt ``ProxyPort``)."""

    def __init__(self, proxy_urls: Sequence[str], *, seed: int) -> None:
        ordered = list(proxy_urls)
        random.Random(seed).shuffle(ordered)
        self._proxies: tuple[str, ...] = tuple(ordered)

    @classmethod
    def from_file(cls, path: Path, *, seed: int) -> WebshareProxyPool:
        """Erstellt den Pool aus einer Webshare-Datei."""
        return cls(parse_webshare_file(path), seed=seed)

    @property
    def size(self) -> int:
        """Anzahl verfuegbarer Proxies im Pool."""
        return len(self._proxies)

    def get(self, index: int) -> str | None:
        """Proxy-URL fuer Slot ``index`` (Modulo); ``None`` bei leerem Pool."""
        return self._proxies[index % len(self._proxies)] if self._proxies else None

    def label_for(self, index: int) -> str:
        """Stabiles, secret-freies Slot-Label (``proxy-<index>``)."""
        return f"proxy-{index}"
