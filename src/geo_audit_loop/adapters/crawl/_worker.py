"""Subprozess-Worker: fuehrt einen advertools-Crawl in isoliertem Reactor aus.

Aufruf: ``python -m geo_audit_loop.adapters.crawl._worker '<json-config>'``.
Grund fuer den Subprozess: Scrapys Twisted-Reactor laesst sich pro Prozess nicht
neu starten, und unter Windows kollidiert die Default-ProactorEventLoop mit Twisten.
Deshalb wird VOR dem advertools-Import die SelectorEventLoopPolicy gesetzt.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any
from urllib.parse import urlsplit


def _main(raw_config: str) -> int:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    import advertools as adv  # Import bewusst nach dem Setzen der EventLoopPolicy

    cfg: dict[str, Any] = json.loads(raw_config)
    domain = str(cfg["domain"])
    url = domain if domain.startswith("http") else f"https://{domain}"
    host = urlsplit(url).netloc

    adv.crawl(
        url_list=url,
        output_file=str(cfg["out_file"]),
        follow_links=True,
        allowed_domains=[host],
        custom_settings={
            "DOWNLOAD_DELAY": float(cfg["download_delay_s"]),
            "CONCURRENT_REQUESTS_PER_DOMAIN": int(cfg["concurrent_per_domain"]),
            "ROBOTSTXT_OBEY": bool(cfg["respect_robots"]),
            "CLOSESPIDER_PAGECOUNT": int(cfg["max_pages"]),
            "DEPTH_LIMIT": 2,
            "USER_AGENT": str(cfg["user_agent"]),
            "LOG_ENABLED": False,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1]))
