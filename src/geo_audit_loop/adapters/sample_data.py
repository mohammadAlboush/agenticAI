"""Deterministische Beispiel-Daten fuer Offline-Demo und Tests (it-sicherheit.de).

Engine-Mock und Crawl-Mock teilen sich diese URLs, damit der Join zwischen
zitierten Quellen und gecrawlten Seiten in der Offline-Demo aufgeht. KEINE echten
Messwerte - nur eine plausible, reproduzierbare Fixture.
"""

from __future__ import annotations

from typing import NamedTuple

from geo_audit_loop.domain.inventory import CrawledPage, PageInventory, SchemaInventory

SAMPLE_DOMAIN = "it-sicherheit.de"


class _Spec(NamedTuple):
    slug: str
    title: str
    meta: str
    jsonld: tuple[str, ...]
    author: bool
    words: int


_SPECS: tuple[_Spec, ...] = (
    _Spec(
        "nis2-richtlinie",
        "NIS2-Richtlinie: Pflichten, Fristen, Umsetzung",
        "Was NIS2 fuer Unternehmen bedeutet und wie die Umsetzung gelingt.",
        ("Article", "FAQPage"),
        True,
        1400,
    ),
    _Spec(
        "ransomware-schutz",
        "Ransomware-Schutz: Massnahmen im Ueberblick",
        "Technische und organisatorische Massnahmen gegen Ransomware.",
        ("Article",),
        True,
        1100,
    ),
    _Spec(
        "zero-trust-architektur",
        "Zero Trust: Architektur Schritt fuer Schritt",
        "Wie ein Zero-Trust-Modell praktisch aufgebaut wird.",
        ("Article", "HowTo"),
        True,
        1300,
    ),
    _Spec(
        "phishing-erkennen",
        "Phishing erkennen: 10 Warnsignale",
        "Woran sich Phishing-Mails zuverlaessig erkennen lassen.",
        ("Article", "FAQPage"),
        False,
        900,
    ),
    _Spec(
        "dsgvo-checkliste",
        "DSGVO-Checkliste fuer KMU",
        "Schritt-fuer-Schritt-Checkliste zur DSGVO-Konformitaet.",
        ("Article", "HowTo", "BreadcrumbList"),
        True,
        1000,
    ),
    _Spec(
        "passwort-manager-vergleich",
        "Passwort-Manager im Vergleich",
        "Funktionen und Sicherheit gaengiger Passwort-Manager.",
        ("Article",),
        False,
        700,
    ),
    _Spec(
        "firewall-grundlagen",
        "Firewall-Grundlagen verstaendlich erklaert",
        "Wie Firewalls arbeiten und worauf es ankommt.",
        ("Article",),
        False,
        600,
    ),
    _Spec(
        "security-awareness-training",
        "Security-Awareness-Training aufbauen",
        "Wie wirksame Awareness-Programme gestaltet werden.",
        ("Article",),
        True,
        1050,
    ),
)


def build_sample_inventory(domain: str = SAMPLE_DOMAIN) -> list[PageInventory]:
    """Baut das reproduzierbare Seiten-Inventar der Beispiel-Domain."""
    items: list[PageInventory] = []
    for spec in _SPECS:
        url = f"https://www.{domain}/{spec.slug}"
        page = CrawledPage(
            url=url,
            status_code=200,
            title=spec.title,
            meta_description=spec.meta,
            h1=(spec.title,),
            h2=("Ueberblick", "Praxis"),
            word_count=spec.words,
            canonical=url,
            lang="de",
        )
        inventory = SchemaInventory(
            url=url,
            jsonld_types=spec.jsonld,
            has_faq="FAQPage" in spec.jsonld,
            has_article="Article" in spec.jsonld,
            has_author=spec.author,
            has_breadcrumb="BreadcrumbList" in spec.jsonld,
            has_opengraph=True,
        )
        items.append(PageInventory(page=page, schema_inventory=inventory))
    return items


def sample_target_urls(domain: str = SAMPLE_DOMAIN) -> list[str]:
    """Die URLs der Beispiel-Seiten (Pool, aus dem der Engine-Mock zitiert)."""
    return [inv.page.url for inv in build_sample_inventory(domain)]
