# Trend-Cockpit

Ein persönliches Werkzeug für dich: Jeden Handelstag nach US-Börsenschluss berechnet ein
Skript, in welchem Trend-Cluster (A/B/C/D) sich rund 500 US-Aktien befinden, und schreibt
die Top-Kandidaten mit einer kurzen KI-Einordnung in eine Datei. Eine Web-App auf deinem
iPhone zeigt dir daraus dein Depot, Verkaufssignale und die heutigen Kaufkandidaten.
Du triffst jede Kauf-/Verkaufsentscheidung selbst und hältst eine kurze Begründung fest.

**Wichtig:** Dieses Tool ist ein Prototyp (Version 1) und keine Anlageberatung. Alle
Entscheidungen und deren Umsetzung beim Broker triffst und verantwortest du selbst.

---

## Was du am Ende hast

- Eine private Web-App-Adresse (z. B. `https://DEIN-GITHUB-NAME.github.io/trend-cockpit/`)
- Die kannst du in Safari öffnen und über "Zum Home-Bildschirm" wie eine normale App
  auf deinem iPhone ablegen
- Sie aktualisiert sich jeden Handelstag automatisch, kostenlos, ohne eigenen Server

## Einmalige Einrichtung (ca. 20–30 Minuten)

### 1. GitHub-Account anlegen
Falls noch nicht vorhanden: auf [github.com](https://github.com) kostenlos registrieren.

### 2. Neues Repository anlegen
- Oben rechts auf **+** → **New repository**
- Name: `trend-cockpit`
- **Public** auswählen. Grund: Mit einem kostenlosen GitHub-Konto funktioniert GitHub Pages
  (Schritt 5) nur bei öffentlichen Repositories. Das ist unbedenklich: Im Repository liegen
  nur Programmcode und öffentliche Kursdaten. Dein Depot und Journal bleiben nur lokal auf
  deinem iPhone, und der API-Key liegt als "Secret" versteckt (Schritt 4), nie im Code.
- **Create repository** klicken

### 3. Projektdateien hochladen
- Im neuen (leeren) Repository auf **"uploading an existing file"** klicken
- Alle Dateien und Ordner aus diesem Projekt per Drag & Drop hineinziehen
  (die Ordnerstruktur mit `.github`, `docs`, `scripts` bleibt dabei erhalten,
  wenn du den ganzen entpackten Projektordner hineinziehst)
- Unten **Commit changes** klicken

### 4. Claude-API-Key als "Secret" hinterlegen
Damit das Skript täglich eine kurze KI-Einordnung zu den Kandidaten schreiben kann:
- Falls noch nicht vorhanden: einen API-Key unter [console.anthropic.com](https://console.anthropic.com)
  erstellen (dort auch etwas Guthaben aufladen — die Kosten liegen bei wenigen Cent pro Tag)
- Im Repository: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
- Name: `ANTHROPIC_API_KEY`
- Wert: dein API-Key
- **Add secret** klicken

Ohne diesen Key funktioniert alles andere trotzdem — nur die Pro/Contra-Kommentare
zu den Kandidaten fehlen dann.

### 5. GitHub Pages aktivieren (macht die App live)
- **Settings** → **Pages**
- Unter "Build and deployment" → **Source**: `Deploy from a branch`
- **Branch**: `main`, Ordner: `/docs` → **Save**
- Nach 1–2 Minuten ist die App erreichbar unter
  `https://DEIN-GITHUB-NAME.github.io/trend-cockpit/`
  (Link findest du auch oben auf der Pages-Einstellungsseite)

### 6. Ersten Skript-Lauf manuell starten
Normalerweise läuft das Skript automatisch werktags nach US-Börsenschluss. Für den
ersten Test musst du nicht warten:
- Im Repository auf den Reiter **Actions**
- Links **"Tägliche Signalberechnung"** auswählen
- Rechts **Run workflow** → **Run workflow** (grüner Button)
- Nach ca. 2–5 Minuten ist der Lauf fertig (grüner Haken) und
  `docs/data/signals.json` wurde mit echten Kursdaten aktualisiert

Falls der Lauf rot markiert ist: auf den Lauf klicken und die Log-Ausgabe lesen,
meist liegt es an einem einzelnen nicht ladbaren Ticker (unkritisch) oder einem
fehlenden/falschen API-Key.

### 7. App auf dem iPhone einrichten
- Die Adresse aus Schritt 5 in **Safari** öffnen (muss Safari sein, nicht Chrome)
- Teilen-Symbol → **"Zum Home-Bildschirm"**
- Ab jetzt öffnet sich die App per Fingertipp wie eine normale App, ganz ohne
  Adressleiste

---

## Laufender Betrieb

- Das Skript läuft automatisch **Montag–Freitag** nach US-Börsenschluss
  (siehe `.github/workflows/daily-signals.yml`, per `workflow_dispatch` auch jederzeit
  manuell über den Actions-Tab startbar)
- Öffne die App morgens, prüfe Verkaufssignale und Kandidaten, entscheide, setze die
  Order ggf. selbst bei deinem Broker um und trage die Entscheidung in der App ein
- Exportiere regelmäßig ein Backup (Einstellungen → Backup exportieren) — Depot und
  Journal liegen **nur lokal auf deinem iPhone**, nicht bei GitHub

## Grenzen von Version 1 (bewusst nicht enthalten)

- Keine automatische Orderausführung — du handelst manuell bei deinem Broker
- Kein Kursverlaufs-Chart in der Detailansicht, nur die Kennzahlen
- Kein Abgleich zwischen mehreren Geräten (Depot/Journal sind an dieses eine iPhone
  gebunden)
- yfinance ist eine inoffizielle Datenquelle und kann gelegentlich ausfallen — die App
  zeigt dir das Datum der letzten Aktualisierung an und warnt bei veralteten Daten

## Wartung / Weiterentwicklung

Die gesamte Logik liegt in zwei Dateien:
- `scripts/generate_signals.py` — Cluster-Regeln, Kandidaten-Auswahl, Claude-Kommentare
- `docs/index.html` — die komplette App (Darstellung + lokale Speicherung)

Änderungswünsche (z. B. andere Cluster-Schwellenwerte, mehr Positionen, anderes
Stop-Verfahren) können direkt in diesen zwei Dateien umgesetzt werden.
