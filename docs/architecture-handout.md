# Ortsbild: Architektur auf einer Seite (Langfassung)

Stand: 11. November 2026. Geschrieben für die Präsentation. Die Kurzfassung (eine Bildschirmseite) liegt als Handout-Seite vor, diese Datei enthält alles in ganzen Sätzen. Quellen sind der Code und die Dokumente [documentation.md](documentation.md), [mvp-plan.md](mvp-plan.md), [plan.md](plan.md) und [dashboard-plan.md](dashboard-plan.md). Kein Rechtsrat.

## Worum es geht

Bürger melden Mängel im öffentlichen Raum mit einem Foto. Unser Server anonymisiert die Meldung, erkennt Kategorie und Gefahr, findet die zuständige Stelle und schreibt den Text. Nach der Freigabe durch die Nutzerin oder den Nutzer erscheint die Meldung im Dashboard. Doppelte Meldungen zählen dort als Stimmen für denselben Fall.

Kennzahlen: ein Sprachmodell (Claude Haiku 5.5) an drei Stellen, zwei lokale Modelle für den Datenschutz (Text und Gesichter), ein Agent (die Recherche der Behörde), sieben Kategorien, zuletzt 571 Backend-Tests, 29 Dashboard-Tests und 84 App-Tests.

## Der Weg einer Meldung

Die Reihenfolge ist fest und läuft als Graph (LangGraph). Jede Stufe sieht nur, was sie braucht. Die Rohdaten verlassen die Datenschutz-Stufe nie.

| Stufe | Was passiert | Art | Sieht |
|---|---|---|---|
| 1. iPhone | Foto, Text, Standort. SwiftUI-App, Anmeldung mit Apple. Eine Meldung ist ein Chat. Vor dem ersten Foto zeigt die App die Foto-Regeln. | App | alles, geht nur über HTTPS an den Server |
| 2. Datenschutz-Schicht (Server) | Metadaten aus dem Foto entfernen, Gesichter abdecken, persönliche Daten im Text durch Platzhalter ersetzen, Nutzerin pseudonymisieren. Im Zweifel wird blockiert. | lokale Modelle und Regeln | die Rohdaten, danach nur noch die bereinigte Form |
| 3. Klassifikation | Kategorie, Gefahr oder Ärgernis, Notfall ja oder nein, Sicherheit des Modells. Die Antwort ist auf ein festes JSON-Schema gezwungen. | Claude Haiku 5.5 | bereinigtes Foto und bereinigter Text |
| 4. Recherche | Findet die zuständige Behörde und den Kontakt. Das Ergebnis wird nachgeprüft und im Register gemerkt. | Claude Haiku 5.5 mit Websuche, dazu Prüfcode | nur Gemeinde, Ortsteil und Kategorie |
| 5. Entwurf | Sachlicher Brief an die Behörde, rund 60 bis 120 Wörter, in der Sprache der Behörde, mit deutscher Zusammenfassung. | Claude Haiku 5.5 | Kategorie, Gefahr, bereinigter Text. Keine Adresse, kein Foto |
| 6. Freigabe | Die Nutzerin prüft Text und Foto, kann das Foto entfernen oder die Meldung löschen. Erst „Freigeben“ macht die Meldung sichtbar. | Mensch | |
| 7. Fälle und Stimmen | Gleiche Kategorie, höchstens 40 m Abstand, 30 Tage offen: derselbe Fall. Jede freigegebene Meldung ist eine Stimme. | Regeln und Code | |
| 8. Dashboard | Karte mit Luftbild und Markern, Liste nach Priorität, Suche nach Ort, Filter nach Kategorie und Priorität. Gleiche Seite im Browser und in der App. | Web | bereinigtes Foto, Beschreibung, Behörde, Entwurf |

Abzweigungen:

- **Notfall erkannt:** Schluss. Es erscheint nur der Hinweis auf 110 und 112, es wird keine Meldung angelegt.
- **Bild unklar** (Kategorie „Sonstiges“ oder Sicherheit unter 0,6): Rückfrage per Tipp. Es wird nicht auf Verdacht recherchiert.
- **Blockiert oder abgelehnt** in der Datenschutz-Stufe: Schluss, die Nutzerin bekommt den Grund genannt.

## Welche Modelle wir nutzen

Alle drei Claude-Aufgaben laufen auf dem kleinen, günstigen Modell. Laut Kommentaren im Code war es auf unserem Testsatz so gut wie die größeren Stufen (die Messdaten dazu stehen im Entscheidungsprotokoll in documentation.md). Jede Aufgabe lässt sich über eine Umgebungsvariable umstellen (`ANTHROPIC_CLASSIFICATION_MODEL`, `ANTHROPIC_RESEARCH_MODEL`, `ANTHROPIC_DRAFT_MODEL`), zum Beispiel auf Sonnet 5.5 für schwierige Orte.

| Modell | Aufgabe | Wo | Besonderheit |
|---|---|---|---|
| Claude Haiku 5.5 (`claude-haiku-5-5`) | Klassifikation, Recherche, Entwurf | Anthropic (USA) | Drei getrennte Aufrufe mit je eigenem Prompt. Klassifikation mit Bild, niedriger Denkaufwand, Schema erzwungen. Recherche mit Websuche, höchstens 4 Suchen. Entwurf ohne Foto und ohne Adresse. |
| GLiNER2-PII (`fastino/gliner2-privacy-filter-PII-multi`) | Namen, Adressen, Kennungen im Text finden | unser Server, CPU | Ergänzt die festen Muster. Treffer werden durch Platzhalter wie `<PERSON>` ersetzt. Lizenz der Trainingsdaten ist noch zu klären. |
| YuNet (ONNX, 227 KB, MIT-Lizenz) | Gesichter im Foto abdecken | unser Server, CPU | Schwelle 0,7, einstellbar mit `FACE_SCORE_THRESHOLD`. Findet kleine Gesichter gut, übersieht manche abgeschnittenen oder nach unten blickenden. Deshalb zusätzlich die Prüfung durch die Nutzerin. |
| Feste Muster (Regeln) | E-Mail, Telefon, IBAN, Kfz-Kennzeichen im Text | unser Server | Kein Modell. Die IBAN wird mit der Prüfsumme gegengeprüft. |
| Notfall-Stichwörter (Regelsuche) | Zweite Sicherung neben dem Modell | unser Server | Mit dem Modell per ODER verknüpft. Ein Text mit „ignoriere die Regeln“ kann den Notfall nicht abschalten. |
| RapidOCR | Namen und Kennzeichen im Foto abdecken | unser Server | Im Code vorhanden, im Betrieb aus (kostet Zeit und Speicher). Kennzeichen im Foto sind deshalb noch nicht abgedeckt. |

Geprüft und nicht genutzt: Apples Gesichtserkennung auf dem iPhone (verworfen, weil später auch Kanäle ohne Handy angebunden werden) und EgoBlur von Meta (stärker, aber rund 400 MB pro Modell, braucht einen größeren Server). Beides bleibt als Option.

## Wo ein Agent arbeitet und wo nur klassifiziert wird

Nur die Recherche handelt wie ein Agent. Der Rest sind einzelne Modellaufrufe oder normale Programmlogik.

**Agent: Recherche der Behörde.**
- Das Modell entscheidet selbst, wonach es sucht, und nutzt das Websuche-Werkzeug (bis zu 4 Suchen, mehrere Runden).
- Es nennt seine Quellen. Danach holt unser Code diese Seiten und prüft, ob der Name der Behörde dort wirklich steht. Ohne lesbare Quelle wird die Antwort verworfen.
- Gefundene Stellen merkt sich ein Register in der Datenbank. Beim zweiten Mal im selben Ort wird nicht erneut gesucht.
- Warum Agent: der Weg zur Antwort ist offen und je nach Gemeinde verschieden.

**Reine Klassifikation: Kategorie, Gefahr, Notfall.**
- Ein einziger Aufruf, keine Werkzeuge, keine Schleife.
- Die Antwort ist auf vier Felder begrenzt: Kategorie (7 Werte), Gefahr oder Ärgernis, Notfall, Sicherheit.
- Das Programm entscheidet danach: bei Notfall Schluss, bei Unsicherheit eine Rückfrage, sonst weiter.
- Der Entwurf ist ebenfalls ein einzelner Aufruf, also Textgenerierung ohne Agent.
- Warum kein Agent: die Aufgabe hat eine feste Form, und eine feste Form lässt sich messen.

**Kein Sprachmodell: Datenschutz, Ablauf, Fälle.**
- Die Datenschutz-Schicht ist ein eigener Graph aus lokalen Modellen und Regeln. Kein Sprachmodell sieht Rohdaten.
- Der Ablauf zwischen den Stufen (Notfall, Rückfrage, weiter) ist Code.
- Duplikate und Stimmen sind eine Abstandsrechnung und eine Zählung.
- Warum Code: hier muss das Ergebnis jedes Mal gleich und prüfbar sein.

Im ursprünglichen Konzept standen zwei Agenten (Recherche und Entwurf) und weitere für später (Duplikate, Regelwerk, Prüfer). Gebaut ist ein Agent.

## Datenschutz

- Anonymisieren vor allem anderen. Was nach der Datenschutz-Stufe kommt, sieht nur die bereinigte Form.
- Im Fehlerfall wird blockiert, nicht durchgelassen.
- Nutzer sind nur ein Pseudonym (Schlüssel-Hash der Apple-ID). Die Apple-ID selbst wird nicht gespeichert.
- Konto löschen entfernt Meldungen, Fotos, Pseudonym und Sitzungen.
- Das Dashboard lädt zur Laufzeit nichts von Dritten. Karten, Schriften und Bilder kommen von unserem Server.

Drei Sicherungen für Fotos:

1. **Vorher:** Beim ersten Foto zeigt die App die Foto-Regeln (nur den Mangel fotografieren, keine Personen).
2. **Währenddessen:** YuNet deckt erkannte Gesichter auf dem Server ab.
3. **Hinterher:** Bei der Freigabe prüft die Nutzerin das bereinigte Foto und trägt die Verantwortung. Sie kann es löschen.

Die Gesichtserkennung ist keine Garantie. Das sagen wir offen und zeigen die drei Schichten statt einer Trefferquote.

## Stand

Der gesamte Entwicklungsstand liegt auf dem Zweig `dashboard` und ist noch nicht committet. Auf dem Server läuft ein älterer Stand, das neueste Design noch nicht.

**Fertig und auf dem Server**
- iOS-App: Foto und Standort, ein Chat pro Meldung, Anmeldung mit Apple, Foto-Regeln, Entwurfskarte mit Freigeben und Löschen, Foto prüfen und entfernen
- Datenschutz-Schicht für Text und Foto
- Klassifikation mit Notfall-Hinweis und Rückfrage bei unklarem Bild
- Recherche mit Prüfung und Register, für jeden Ort
- Entwurf ohne Adresse und ohne Foto
- Freigabe, Fälle und Stimmen
- Dashboard: Karte, Liste, Ortssuche, Filter, auch in der App
- Betrieb: IONOS Cube mit HTTPS, PostgreSQL, S3-Speicher
- Skript, das Testmeldungen über die echte Schnittstelle anlegt

**Gebaut, noch nicht deployt**
- Neues Dashboard-Design: Luftbild von Stuttgart (Landesamt für Geoinformation BW, offene Daten, 278 MB), Glas-Optik, Fotos in Schwarz-Weiß
- Filter nach Kategorie und Priorität als Dropdown
- Neues Aussehen der App im Stil des Dashboards

Die Lizenz der Luftbilder verlangt die Quellenangabe, sie steht unten rechts auf der Karte.

**Geplant, noch nicht gebaut**
- Überarbeiten: die Nutzerin ergänzt den Entwurf
- Wöchentliche Zusammenfassung per E-Mail an die Behörde, statt einzelner Briefe
- Zugang für Behörden und eine zweite Ansicht
- Regelwerk für Autonomie-Stufen und ein Prüfer-Agent
- Das Modell betrachtet beim Entwurf das bereinigte Foto
- Kennzeichen im Foto abdecken, stärkere Gesichtserkennung messen
- Weitere Städte (Luftbild nur für Stuttgart)
- Weitere Eingangskanäle über ein Gateway, etwa E-Mail

## Offen, bevor die App öffentlich wird

**Recht**
- Auftragsverarbeitung mit IONOS (Server) und Anthropic (US-Anbieter) steht aus.
- Trainingsdaten von YuNet und GLiNER2: Lizenz klären lassen.
- Nutzungsbedingungen und der Satz zur Verantwortung bei der Freigabe: juristisch prüfen.

**Technik**
- Das Dashboard hat keinen Login. Aktuell zeigt es für Tests alle freigegebenen Meldungen aller Nutzer (`DEMO_REPORTER_IDS`). Das muss vor TestFlight oder App Store weg.
- Die Trefferquote der Gesichtserkennung bei schwierigen Fotos ist nicht gemessen.
- Die Speicher-Spitze des Servers bei einer echten Meldung ist nicht gemessen (leer 2,3 GB von 3,8 GB).
- Begrenzung für den Anmelde-Endpunkt, Logs mit Alarm, Löschen der Apple-ID beim Konto löschen.

## Technik auf einen Blick

| Bereich | Umsetzung |
|---|---|
| App | Swift, SwiftUI, native iOS 26, Swift Testing |
| Backend | Python, FastAPI, Pydantic, LangGraph (zwei Graphen: Datenschutz und Ablauf) |
| Daten | PostgreSQL im Container, Fotos im IONOS S3-Speicher |
| Hosting | IONOS Cube Basic S (2 vCPU, 4 GB RAM), Caddy mit HTTPS |
| Anmeldung | Sign in with Apple, eigene Sitzungen mit rotierenden Tokens |
| Dashboard | HTML, CSS, JavaScript ohne Build, Leaflet und MapLibre, Karten als PMTiles vom eigenen Server |
| Karte | OpenStreetMap-Daten über Protomaps für die Namen, Luftbild des Landesamts BW für den Grund |
| Ortssuche | Nominatim (OpenStreetMap) über unseren Server, es verlässt nur der getippte Text das Haus |
| Dritte zur Laufzeit | Anthropic (Klassifikation, Recherche, Entwurf) und Nominatim. Sonst keine. |
| Kategorien | Müll, Graffiti, Straßenlaterne, Spielgerät, Schlagloch, Baum, Sonstiges |
