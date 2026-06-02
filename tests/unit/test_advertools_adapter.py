"""Phase-4-Gate: advertools-Adapter-Wiring (Subprozess gemockt, kein Netz)."""

from __future__ import annotations

import json
import subprocess

import pytest

from geo_audit_loop.adapters.crawl.advertools_crawler import AdvertoolsCrawlAdapter
from geo_audit_loop.domain.errors import CrawlError
from geo_audit_loop.domain.inventory import CrawlOptions

_FIXTURE = (
    '{"url":"https://www.it-sicherheit.de/nis2","status":200,"title":"NIS2","jsonld_0":"Article"}\n'
)


def _opts() -> CrawlOptions:
    return CrawlOptions(user_agent="test-agent")


def test_adapter_parses_worker_output(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        from pathlib import Path

        cfg = json.loads(args[-1])
        Path(cfg["out_file"]).write_text(_FIXTURE, encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    pages = AdvertoolsCrawlAdapter().crawl("it-sicherheit.de", _opts())
    assert len(pages) == 1
    assert pages[0].page.title == "NIS2"
    assert pages[0].schema_inventory.has_article is True


def test_adapter_raises_on_nonzero_returncode(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 1, "", "boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(CrawlError):
        AdvertoolsCrawlAdapter().crawl("x.de", _opts())


def test_adapter_returns_empty_when_no_output(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert AdvertoolsCrawlAdapter().crawl("x.de", _opts()) == []
