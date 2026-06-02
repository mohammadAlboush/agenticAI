"""Smoke-Test: Package importierbar, Version vorhanden (Phase-0-Gate)."""

from __future__ import annotations

import geo_audit_loop


def test_package_has_version() -> None:
    assert geo_audit_loop.__version__
    assert isinstance(geo_audit_loop.__version__, str)
