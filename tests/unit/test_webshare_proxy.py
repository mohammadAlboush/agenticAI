"""Phase-4-Gate: Webshare-Parsing und seed-deterministische Proxy-Rotation."""

from __future__ import annotations

from pathlib import Path

import pytest

from geo_audit_loop.adapters.proxy.webshare import WebshareProxyPool, parse_webshare_file
from geo_audit_loop.domain.errors import ProxyError


def test_parse_webshare_file(tmp_path: Path) -> None:
    path = tmp_path / "proxies.txt"
    path.write_text("1.2.3.4:8000:user:pass\n5.6.7.8:9000:u2:p2\n\n", encoding="utf-8")
    assert parse_webshare_file(path) == [
        "http://user:pass@1.2.3.4:8000",
        "http://u2:p2@5.6.7.8:9000",
    ]


def test_parse_rejects_malformed_line(tmp_path: Path) -> None:
    path = tmp_path / "p.txt"
    path.write_text("nur:drei:teile\n", encoding="utf-8")
    with pytest.raises(ProxyError):
        parse_webshare_file(path)


def test_parse_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ProxyError):
        parse_webshare_file(tmp_path / "does-not-exist.txt")


def test_pool_is_seed_deterministic_permutation() -> None:
    urls = [f"http://u:p@10.0.0.{i}:8000" for i in range(10)]
    pool_a = WebshareProxyPool(urls, seed=42)
    pool_b = WebshareProxyPool(urls, seed=42)
    seq_a = [pool_a.get(i) for i in range(10)]
    seq_b = [pool_b.get(i) for i in range(10)]
    assert seq_a == seq_b
    assert set(seq_a) == set(urls)
    assert pool_a.size == 10


def test_pool_wraps_modulo_and_labels() -> None:
    urls = ["http://u:p@10.0.0.1:8000", "http://u:p@10.0.0.2:8000"]
    pool = WebshareProxyPool(urls, seed=1)
    assert pool.get(0) == pool.get(2)
    assert pool.label_for(3) == "proxy-3"


def test_empty_pool_returns_none() -> None:
    pool = WebshareProxyPool([], seed=1)
    assert pool.size == 0
    assert pool.get(0) is None
