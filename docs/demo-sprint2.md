# Sprint-2-Demo — Live-Ablauf (offline, deterministisch)

> Ziel der Demo: in **einem** Befehl zeigen, wie der Loop von der Messung (*was* wird zitiert)
> zum Verständnis (*warum*) und zur Maßnahme (*was tun*) kommt — reproduzierbar, ohne Netz/Kosten.

## Voraussetzung

```bash
uv sync        # einmalig; venv + Abhängigkeiten
```

## Der eine Befehl

```bash
uv run python -m geo_audit_loop --domain it-sicherheit.de --offline --explain --top-n 3 --log-level WARNING
```

- `--offline` → deterministische Mock-Engines **und** Mock-Reasoning (Seed 42).
- `--explain` → hängt den Sprint-2-Lern-Loop an (Pattern-Miner + GEO-Auditor).
- `--log-level WARNING` → unterdrückt die JSON-Logzeilen für eine saubere Demo-Ausgabe.

## Was passiert (3 Akte)

1. **WAS** — Sampler (240 Probes) + Crawler erzeugen die Top/Flop-Sichtbarkeitsliste.
2. **WARUM** — der **Pattern-Miner** mint aus den Top-Seiten 3 Best-Practice-`Template`s
   (verankert in den 10 Hebeln + Citation-Pyramide).
3. **WAS TUN** — der **GEO-Auditor** prüft die Flop-Seiten gegen die Templates und liefert
   6 nach Pyramide **priorisierte** `AuditFinding`s.

## Erwartete Ausgabe (gekürzt, Seed 42 → exakt reproduzierbar)

```
=== GEO-Sichtbarkeit: it-sicherheit.de ===
TOP   1.  71x  /nis2-richtlinie   2.  42x  /ransomware-schutz   3.  39x  /zero-trust-architektur
FLOP  1.   7x  /security-awareness-training   2.  17x  /passwort-manager-vergleich   3.  19x  /firewall-grundlagen

=== WARUM ranken die Top-Seiten? 3 Muster (Pattern-Miner) ===
  [t1] Extrahierbarer Antwortblock + FAQ-Schema   (Konfidenz 0.82)
       Ebene: Extrahierbarkeit & Struktur | Hebel: Antwortbloecke, Maschinenlesbare Struktur
  [t2] Autor-Entitaet + Faktendichte              (Konfidenz 0.76)
  [t3] Schritt-fuer-Schritt-Struktur (HowTo)      (Konfidenz 0.71)

=== WAS tun? 6 Findings (GEO-Auditor, priorisiert) ===
  1. [HIGH]   /passwort-manager-vergleich   Extrahierbarkeit · Maschinenlesbare Struktur
             Fix: Vergleichstabelle + Product/Review-Schema ergaenzen.
  2. [MEDIUM] /firewall-grundlagen          Extrahierbarkeit · Definitionsbloecke
  3. [MEDIUM] /security-awareness-training   Extrahierbarkeit · Antwortbloecke
  4. [HIGH]   /firewall-grundlagen          Substanz · Faktendichte
  5. [MEDIUM] /passwort-manager-vergleich   Substanz · Entitaeten-Klarheit
  6. [LOW]    /security-awareness-training   Zitation · Frage-Deckung
```

## Sprechzettel (3 Sätze)

1. „Sprint 1 sagt mir, dass `/passwort-manager-vergleich` selten zitiert wird — aber nicht warum."
2. „Der Pattern-Miner zeigt: Top-Seiten haben FAQ-Schema und einen extrahierbaren Antwortblock."
3. „Der GEO-Auditor sagt mir priorisiert, was genau zu tun ist — und Sprint 3 setzt es um."

## Determinismus zeigen

Den Befehl **zweimal** ausführen → identische Zahlen und Reihenfolge. Das ist das
Master-Kriterium: der Lern-Loop ist trotz LLM-Schritten reproduzierbar (Mock-Reasoning).

## Optional: echtes Claude-Reasoning (nicht für die Live-Demo nötig)

```bash
# .env mit ANTHROPIC_API_KEY, dann:
GEO_LIVE_ENGINES=claude uv run python -m geo_audit_loop --domain it-sicherheit.de --explain
```

## Begleitend

- Folien: `docs/sprint2-praesentation.html` (Tab „Live-Demo" spiegelt genau diese Ausgabe).
- Tests/Evals: `uv run pytest` (toleranzbasierte Eval-Slots für beide Agenten).
