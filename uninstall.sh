#!/bin/bash
# Kimai Auto Tracker - Deinstallation

APP_NAME="kimai-tracker"
INSTALL_DIR="$HOME/.local/share/$APP_NAME"
BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/kimai-tracker"

echo "Kimai Auto Tracker – Deinstallation"
echo ""

read -p "Möchtest du auch die Konfiguration löschen? (j/N) " del_config

# Remove files
rm -rf "$INSTALL_DIR"
rm -f "$BIN_DIR/kimai-tracker"
rm -f "$HOME/.local/share/applications/kimai-tracker.desktop"
rm -f "$HOME/.local/share/icons/hicolor/scalable/apps/kimai-tracker.svg"
rm -f "$HOME/.config/autostart/kimai-tracker.desktop"

if [[ "$del_config" =~ ^[jJyY]$ ]]; then
    rm -rf "$CONFIG_DIR"
    echo "✓ Konfiguration gelöscht."
fi

update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor/" 2>/dev/null || true

echo "✓ Kimai Auto Tracker wurde deinstalliert."
