#!/bin/bash
# ============================================
# Kimai Auto Tracker - Installer für Zorin OS 18
# ============================================

set -e

APP_NAME="kimai-tracker"
INSTALL_DIR="$HOME/.local/share/$APP_NAME"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"

echo "╔══════════════════════════════════════════╗"
echo "║   Kimai Auto Tracker - Installation      ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# --- 1. System-Abhängigkeiten prüfen ---
echo "▸ Prüfe System-Abhängigkeiten …"

MISSING_PKGS=""

# Check for GTK4 and libadwaita (should be present on Zorin OS 18)
if ! python3 -c "import gi; gi.require_version('Gtk', '4.0')" 2>/dev/null; then
    MISSING_PKGS="$MISSING_PKGS gir1.2-gtk-4.0"
fi

if ! python3 -c "import gi; gi.require_version('Adw', '1')" 2>/dev/null; then
    MISSING_PKGS="$MISSING_PKGS gir1.2-adw-1"
fi

if ! python3 -c "import requests" 2>/dev/null; then
    MISSING_PKGS="$MISSING_PKGS python3-requests"
fi

if [ -n "$MISSING_PKGS" ]; then
    echo "  → Installiere fehlende Pakete:$MISSING_PKGS"
    sudo apt install -y $MISSING_PKGS
else
    echo "  ✓ Alle Abhängigkeiten vorhanden."
fi

# --- 2. Dateien installieren ---
echo ""
echo "▸ Installiere Anwendungsdateien …"

mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"
mkdir -p "$DESKTOP_DIR"
mkdir -p "$ICON_DIR"

# Copy main script
cp "$(dirname "$0")/kimai_tracker.py" "$INSTALL_DIR/kimai_tracker.py"
chmod +x "$INSTALL_DIR/kimai_tracker.py"

# Create launcher script
cat > "$BIN_DIR/kimai-tracker" << LAUNCHER
#!/bin/bash
exec python3 "$INSTALL_DIR/kimai_tracker.py" "\$@"
LAUNCHER
chmod +x "$BIN_DIR/kimai-tracker"

echo "  ✓ Dateien installiert nach $INSTALL_DIR"

# --- 3. SVG-Icon erstellen ---
echo ""
echo "▸ Erstelle Icon …"

cat > "$ICON_DIR/kimai-tracker.svg" << 'ICON'
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#3584e4"/>
      <stop offset="100%" style="stop-color:#1a73e8"/>
    </linearGradient>
  </defs>
  <rect width="64" height="64" rx="14" fill="url(#bg)"/>
  <circle cx="32" cy="32" r="18" fill="none" stroke="white" stroke-width="3"/>
  <line x1="32" y1="32" x2="32" y2="19" stroke="white" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="32" y1="32" x2="42" y2="32" stroke="white" stroke-width="2.5" stroke-linecap="round"/>
  <circle cx="32" cy="32" r="2.5" fill="white"/>
  <circle cx="52" cy="14" r="6" fill="#2ec27e"/>
  <path d="M49 14 l2 2 4-4" stroke="white" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
ICON

echo "  ✓ Icon erstellt."

# --- 4. Desktop-Datei erstellen ---
echo ""
echo "▸ Erstelle Desktop-Eintrag …"

cat > "$DESKTOP_DIR/kimai-tracker.desktop" << DESKTOP
[Desktop Entry]
Type=Application
Name=Kimai Auto Tracker
Comment=Automatische Zeiterfassung mit Kimai
Exec=$BIN_DIR/kimai-tracker
Icon=kimai-tracker
Terminal=false
Categories=Utility;Office;ProjectManagement;
Keywords=time;tracking;kimai;zeiterfassung;
StartupNotify=true
DESKTOP

# Update icon cache
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor/" 2>/dev/null || true
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

echo "  ✓ Desktop-Eintrag erstellt."

# --- 5. PATH prüfen ---
echo ""
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "▸ Hinweis: $BIN_DIR ist nicht in deinem PATH."
    echo "  Füge folgende Zeile zu ~/.bashrc hinzu:"
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
fi

# --- Fertig ---
echo "╔══════════════════════════════════════════╗"
echo "║   ✓ Installation abgeschlossen!          ║"
echo "╠══════════════════════════════════════════╣"
echo "║                                          ║"
echo "║  Starten:                                ║"
echo "║    kimai-tracker                         ║"
echo "║                                          ║"
echo "║  Oder über das Anwendungsmenü:           ║"
echo "║    → 'Kimai Auto Tracker'                ║"
echo "║                                          ║"
echo "║  Hintergrund-Modus (Autostart):          ║"
echo "║    kimai-tracker --background            ║"
echo "║                                          ║"
echo "╚══════════════════════════════════════════╝"
