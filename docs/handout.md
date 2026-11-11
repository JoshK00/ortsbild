# Ortsbild: Architektur in Kürze

Stand: 11. November 2026. Die Langfassung steht in [architecture-handout.md](architecture-handout.md).

Foto machen, Server anonymisiert, Claude ordnet ein und recherchiert die Behörde, die Nutzerin gibt frei, das Dashboard zeigt den Fall. Doppelte Meldungen werden Stimmen.

## Der Weg einer Meldung

| Stufe | Art | Was |
|---|---|---|
| 1. iPhone-App | App | Foto, Text, Standort |
| 2. Datenschutz | lokale Modelle | Gesichter und persönliche Daten raus, bevor irgendein Sprachmodell etwas sieht |
| 3. Klassifikation | Claude | Kategorie, Gefahr, Notfall |
| 4. Recherche | Claude mit Websuche | zuständige Behörde |
| 5. Entwurf | Claude | Brieftext |
| 6. Freigabe | Mensch | Nutzerin prüft Text und Foto |
| 7. Fälle und Stimmen | Regeln und Code | gleicher Fall: bis 40 m, 30 Tage |
| 8. Dashboard | Web | Karte, Liste, Suche, Filter |

Abzweigungen: bei einem **Notfall** erscheint nur der Hinweis auf 110 und 112. Ist das **Bild unklar**, fragt die App die Nutzerin.

## Modelle

| Modell | Aufgabe | Wo |
|---|---|---|
| Claude Haiku 5.5 | Klassifikation, Recherche, Entwurf (drei getrennte Aufrufe) | Anthropic, USA |
| GLiNER2-PII | persönliche Daten im Text | unser Server |
| YuNet | Gesichter im Foto abdecken | unser Server |

## Agent oder Klassifikation?

- **Agent:** die Recherche der Behörde. Sie sucht selbst im Web, nennt Quellen, und unser Code prüft sie nach.
- **Klassifikation:** Kategorie, Gefahr und Notfall in einem Aufruf mit festem Antwortschema. Der Entwurf ist ebenfalls ein einzelner Aufruf.
- **Kein Sprachmodell:** Datenschutz, Ablauf und Fälle. Lokale Modelle und Regeln, kein Sprachmodell sieht Rohdaten.

## Stand

**Fertig**
- App MVP, Datenschutz, Klassifikation, Recherche, Entwurf
- Freigabe, Fälle, Stimmen
- Dashboard mit Suche und Filter, läuft auf dem Server

**Geplant**
- App: "Überarbeiten"-Feature entwickeln
- Zugang für Behörden
- Wöchentliche E-Mail an die Behörde
