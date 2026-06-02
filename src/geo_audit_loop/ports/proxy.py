"""Port: Beschaffung rotierender Proxy-Endpunkte."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ProxyPort(Protocol):
    """Liefert authentifizierte Proxy-URLs (``http://user:pass@ip:port``) zur Rotation.

    Index-basiert statt round-robin, damit der Sampler die 5-IP-Dimension
    deterministisch und reproduzierbar (seed-gesteuert) durchlaufen kann. Ein leerer
    Pool ist erlaubt (``size == 0`` -> ``get`` liefert ``None`` = Direktverbindung).
    """

    @property
    def size(self) -> int:
        """Anzahl verfuegbarer Proxies im Pool."""
        ...

    def get(self, index: int) -> str | None:
        """Proxy-URL fuer Slot ``index`` (deterministisch, Modulo); ``None`` bei leerem Pool."""
        ...

    def label_for(self, index: int) -> str:
        """Stabiles, secret-freies Label fuer Slot ``index`` (z.B. ``"proxy-3"``)."""
        ...
