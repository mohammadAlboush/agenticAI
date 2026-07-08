"""Deterministische Beispiel-Daten fuer Offline-Demo und Tests (it-sicherheit.de).

Engine-Mock und Crawl-Mock teilen sich diese URLs, damit der Join zwischen
zitierten Quellen und gecrawlten Seiten in der Offline-Demo aufgeht. KEINE echten
Messwerte - nur eine plausible, reproduzierbare Fixture. Der ``body``-Auszug ist bei
Top-Seiten faktenreich, bei Flop-Seiten bewusst duenn (Grundlage inhaltlicher Audits).
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
    body: str


_SPECS: tuple[_Spec, ...] = (
    _Spec(
        "nis2-richtlinie",
        "NIS2-Richtlinie: Pflichten, Fristen, Umsetzung",
        "Was NIS2 fuer Unternehmen bedeutet und wie die Umsetzung gelingt.",
        ("Article", "FAQPage"),
        True,
        1400,
        "Die NIS2-Richtlinie ist ein EU-Gesetz zur Cybersicherheit, das seit Oktober 2024 gilt. "
        "Betroffen sind rund 30.000 Unternehmen in Deutschland ab 50 Mitarbeitenden oder 10 Mio. "
        "Euro Umsatz in 18 Sektoren. Pflichten: Risikomanagement, Meldung erheblicher Vorfaelle "
        "binnen 24 Stunden, Nachweispflicht und Haftung der Geschaeftsleitung.",
    ),
    _Spec(
        "ransomware-schutz",
        "Ransomware-Schutz: Massnahmen im Ueberblick",
        "Technische und organisatorische Massnahmen gegen Ransomware.",
        ("Article",),
        True,
        1100,
        "Ransomware verschluesselt Daten und erpresst Loesegeld. Wirksamer Schutz kombiniert "
        "Offline-Backups nach dem 3-2-1-Prinzip, konsequentes Patch-Management, Netzwerk-"
        "Segmentierung und Multi-Faktor-Authentifizierung. Laut BSI ist ein getestetes "
        "Wiederherstellungs-Konzept der wichtigste Einzelfaktor fuer die Resilienz.",
    ),
    _Spec(
        "zero-trust-architektur",
        "Zero Trust: Architektur Schritt fuer Schritt",
        "Wie ein Zero-Trust-Modell praktisch aufgebaut wird.",
        ("Article", "HowTo"),
        True,
        1300,
        "Zero Trust folgt dem Grundsatz 'never trust, always verify': jeder Zugriff wird "
        "unabhaengig vom Standort geprueft. Schritt 1: Schutzbedarf und Datenfluesse erfassen. "
        "Schritt 2: Identitaeten und Geraete staerken (MFA, Geraete-Compliance). Schritt 3: "
        "Mikrosegmentierung und kontinuierliche Auswertung. Der Aufbau erfolgt iterativ, nicht "
        "als Big Bang.",
    ),
    _Spec(
        "phishing-erkennen",
        "Phishing erkennen: 10 Warnsignale",
        "Woran sich Phishing-Mails zuverlaessig erkennen lassen.",
        ("Article", "FAQPage"),
        False,
        900,
        "Phishing-Mails taeuschen einen vertrauenswuerdigen Absender vor. Typische Warnsignale "
        "sind unpersoenliche Anrede, kuenstlicher Zeitdruck, abweichende Absenderdomains, "
        "Rechtschreibfehler und Links, deren Ziel beim Mouseover nicht zur Marke passt. Im "
        "Zweifel den Absender ueber einen bekannten Kanal verifizieren, nie auf Links klicken.",
    ),
    _Spec(
        "dsgvo-checkliste",
        "DSGVO-Checkliste fuer KMU",
        "Schritt-fuer-Schritt-Checkliste zur DSGVO-Konformitaet.",
        ("Article", "HowTo", "BreadcrumbList"),
        True,
        1000,
        "Diese Checkliste fuehrt KMU in sieben Schritten zur DSGVO-Konformitaet: Verzeichnis der "
        "Verarbeitungstaetigkeiten anlegen, Rechtsgrundlagen pruefen, technisch-organisatorische "
        "Massnahmen dokumentieren, Auftragsverarbeiter-Vertraege schliessen, Betroffenenrechte "
        "operationalisieren, Meldewege fuer Datenpannen definieren und regelmaessig auditieren.",
    ),
    _Spec(
        "passwort-manager-vergleich",
        "Passwort-Manager im Vergleich",
        "Funktionen und Sicherheit gaengiger Passwort-Manager.",
        ("Article",),
        False,
        700,
        "Passwort-Manager speichern Zugangsdaten verschluesselt. Es gibt viele gute Loesungen am "
        "Markt mit unterschiedlichen Funktionen. Am besten probiert man ein paar aus und waehlt "
        "den, der am besten gefaellt.",
    ),
    _Spec(
        "firewall-grundlagen",
        "Firewall-Grundlagen verstaendlich erklaert",
        "Wie Firewalls arbeiten und worauf es ankommt.",
        ("Article",),
        False,
        600,
        "Eine Firewall schuetzt das Netzwerk. Sie filtert den Datenverkehr und ist sehr wichtig "
        "fuer die Sicherheit. Jedes Unternehmen sollte eine haben.",
    ),
    _Spec(
        "security-awareness-training",
        "Security-Awareness-Training aufbauen",
        "Wie wirksame Awareness-Programme gestaltet werden.",
        ("Article",),
        True,
        1050,
        "Security-Awareness-Trainings sensibilisieren Mitarbeitende fuer Gefahren. Sie sind ein "
        "wichtiger Baustein der Sicherheit und sollten regelmaessig stattfinden.",
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
            content=spec.body,
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
