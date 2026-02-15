# Kimai Auto Tracker

Automatische Zeiterfassung für [Kimai 2](https://www.kimai.org/) basierend auf Aktivitätserkennung – entwickelt für Zorin OS 18 (GNOME/Wayland).

## Funktionen

- **Automatische Aktivitätserkennung** über `org.gnome.Mutter.IdleMonitor` (D-Bus) – voll kompatibel mit Wayland
- **Automatisches Starten/Pausieren** der Kimai-Zeiterfassung bei Aktivität/Inaktivität
- **Notification mit Schnellauswahl** – beim Start erscheint eine Benachrichtigung, über die du sofort Projekt und Aufgabe ändern kannst
- **GTK4/Libadwaita GUI** – fügt sich nahtlos in Zorin OS 18 ein
- **Autostart-Unterstützung** – kann beim Systemstart automatisch im Hintergrund starten
- **Konfigurierbar** – Idle-Timeout, Prüfintervall, Standard-Projekt/-Aufgabe

## Systemvoraussetzungen

- Zorin OS 18 (oder Ubuntu 24.04+ mit GNOME/Wayland)
- Python 3.10+
- GTK 4, Libadwaita 1
- python3-requests

## Installation

```bash
chmod +x install.sh
./install.sh
```

Das Installationsskript:
1. Prüft und installiert fehlende Abhängigkeiten
2. Kopiert die Anwendung nach `~/.local/share/kimai-tracker/`
3. Erstellt einen Launcher in `~/.local/bin/`
4. Erstellt einen Desktop-Eintrag im Anwendungsmenü
5. Installiert das App-Icon

## Benutzung

### Erster Start

1. Starte **Kimai Auto Tracker** über das Anwendungsmenü oder mit `kimai-tracker`
2. Öffne die **Einstellungen** (Zahnrad-Symbol)
3. Gib deine **Kimai URL** ein (z.B. `https://kimai.example.com`)
4. Gib deinen **API Token** ein (findest du in Kimai unter Profil → API)
5. Teste die Verbindung
6. Lade Projekte & Aufgaben und wähle ein **Standard-Projekt** und eine **Standard-Aufgabe**
7. Speichere die Einstellungen
8. Klicke **Überwachung starten**

### Workflow

Sobald die Überwachung aktiv ist:

1. **Du arbeitest** → Kimai-Zeiterfassung startet automatisch mit dem Standard-Projekt
2. **Notification erscheint** → Klicke darauf, um Projekt/Aufgabe zu ändern
3. **Du bist inaktiv** (konfigurierbar, Standard: 10 Min.) → Zeiterfassung wird pausiert
4. **Du kehrst zurück** → Zeiterfassung wird automatisch fortgesetzt

### Autostart

Aktiviere in den Einstellungen "Beim Systemstart automatisch starten", damit das Tool im Hintergrund startet.

## Kimai API Token

1. Melde dich in deiner Kimai-Instanz an
2. Gehe zu **Profil** → **API**
3. Erstelle einen neuen API-Token
4. Kopiere den Token in die Einstellungen des Trackers

## Konfiguration

Die Konfigurationsdatei liegt unter `~/.config/kimai-tracker/config.json`.

## Logs

Logs werden geschrieben nach `~/.config/kimai-tracker/kimai-tracker.log`.

## Deinstallation

```bash
chmod +x uninstall.sh
./uninstall.sh
```

## Technische Details

- **Idle Detection**: Nutzt `org.gnome.Mutter.IdleMonitor.GetIdletime` über D-Bus – funktioniert unter Wayland ohne besondere Berechtigungen
- **GUI Framework**: GTK 4 + Libadwaita (nativ für GNOME/Zorin)
- **API**: Kimai 2 REST API mit Bearer-Token-Authentifizierung
- **Polling**: Prüft die Idle-Zeit in konfigurierbarem Intervall (Standard: 15 Sekunden)
