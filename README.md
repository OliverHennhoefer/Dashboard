# Template Dashboard: Umweltmonitoring

Dieses Projekt erstellt ein einfaches **Web-Dashboard**, das Sensordaten von einer [SenseBox](https://sensebox.de/) sammelt und visualisiert – mit **TimescaleDB** zur Speicherung und **Dash (von Plotly)** zur Darstellung.

---

## 📦 Was macht dieses Projekt?

- ⬇ **Lädt Sensordaten live** von der openSenseMap API herunter.
- 🗄️ **Speichert** die Daten in einer PostgreSQL-Datenbank (mit TimescaleDB für Zeitreihen).
- 📊 **Zeigt interaktive Diagramme** für jeden Sensor im Browser an (z. B. Temperatur, Luftfeuchtigkeit).

---

## 🧱 Projektstruktur

```
.
├── app/                  # Python Dash App
│   ├── app.py            # Holt Daten, speichert sie, erstellt das Dashboard
│   ├── Dockerfile        # Containerdefinition für die App/das Dashboard
│   └── requirements.txt  # Python-Abhängigkeiten
├── init-db/
│   └── init.sql          # SQL-Skript für die Datenbankschema
├── docker-compose.yaml   # Verbindet App & Datenbank
├── .gitignore            # Dateien, die Git ignorieren soll
├── LICENSE
└── README.md             # Diese Datei!
```

---

## 🚀 So startest du das Projekt

Voraussetzung: **Docker** und **Docker Compose** müssen installiert sein.

1. Setze Docker und WSL auf (siehe Vorlesungsunterlagen)
2. Repository klonen und ins Projektverzeichnis wechseln.
3. Starte das Projekt mit:

```bash
docker-compose up --build
```

(dein Terminal muss auf das aktuelle Projektverzeichnis mit der `docker-compose.yaml` zeigen)

4. Öffne deinen Browser und gehe zu:  
   👉 [http://localhost:8050](http://localhost:8050)

---

## 🧠 Wie funktioniert das?

- `app.py`:
  - Ruft Metadaten und Messwerte von einer SenseBox ab.
  - Schreibt neue Daten in die TimescaleDB.
  - Liest Daten aus der DB und visualisiert sie mit Plotly.

- `init.sql`:  
  - Erstellt eine `sensor_data`-Tabelle.
  - Wandelt sie in eine TimescaleDB-Hypertable um.

- `docker-compose.yaml`:  
  - Startet zwei Container:
    - Eine TimescaleDB-Datenbank
    - Eine Python Dash App

---

## ⚙️ Konfiguration

Die SenseBox-ID kannst du in der Datei `docker-compose.yaml` unter `SENSEBOX_ID` setzen.  
Ersetze den Standardwert mit der ID deiner eigenen SenseBox von [opensensemap.org](https://opensensemap.org/).

---

## 📚 Abhängigkeiten

Du musst **nichts manuell installieren** – alle Abhängigkeiten (Python Bibliotheken) werden automatisch über Docker geladen.
Auf deinem System läuft so gesehen lokal nichts. Der Code wird in den Containern ausgeführt (die man sich wie kleine Server,
abgekapselt von deinem übrigen System, vorstellen kann)

---

## 🧼 Stoppen des Projekts

Zum Beenden der Container:

```bash
docker-compose down
```

---

## Fragen?

oliver.hennhoefer@h-ka.de