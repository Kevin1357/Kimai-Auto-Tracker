#!/usr/bin/env python3
"""
Kimai Auto Time Tracker
Automatically tracks work time via Kimai 2 API based on user activity detection.
Uses GNOME Mutter IdleMonitor (DBus) for Wayland-compatible idle detection.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

import json
import os
import sys
import threading
import time
import logging
from datetime import datetime
from pathlib import Path
from enum import Enum

import requests
from gi.repository import Gtk, Adw, GLib, Gio

# --- Constants ---
APP_ID = "de.ferienlotse.kimai-tracker"
APP_NAME = "Kimai Auto Tracker"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kimai-tracker"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = CONFIG_DIR / "kimai-tracker.log"
AUTOSTART_DIR = Path.home() / ".config" / "autostart"
AUTOSTART_FILE = AUTOSTART_DIR / "kimai-tracker.desktop"
DESKTOP_FILE_PATH = Path("/usr/share/applications/kimai-tracker.desktop")

# --- Logging ---
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


class TrackingState(Enum):
    STOPPED = "stopped"
    TRACKING = "tracking"
    PAUSED = "paused"


# --- Default Config ---
DEFAULT_CONFIG = {
    "kimai_url": "",
    "api_token": "",
    "idle_timeout_minutes": 10,
    "default_project_id": None,
    "default_activity_id": None,
    "autostart": False,
    "poll_interval_seconds": 15,
    "resume_grace_seconds": 30,
}


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
            merged = {**DEFAULT_CONFIG, **cfg}
            return merged
        except Exception as e:
            log.error(f"Fehler beim Laden der Konfiguration: {e}")
    return dict(DEFAULT_CONFIG)


def save_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    log.info("Konfiguration gespeichert.")


# ========== Kimai API Client ==========
class KimaiClient:
    def __init__(self, base_url, api_token):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        })

    def _url(self, path):
        return f"{self.base_url}/api/{path.lstrip('/')}"

    def test_connection(self):
        try:
            r = self.session.get(self._url("ping"), timeout=10)
            return r.status_code == 200
        except Exception as e:
            log.error(f"Verbindungstest fehlgeschlagen: {e}")
            return False

    def get_projects(self):
        try:
            r = self.session.get(self._url("projects"), params={"visible": "1"}, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(f"Projekte laden fehlgeschlagen: {e}")
            return []

    def get_activities(self, project_id=None):
        try:
            params = {"visible": "1"}
            if project_id:
                params["project"] = project_id
            r = self.session.get(self._url("activities"), params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(f"Aktivitäten laden fehlgeschlagen: {e}")
            return []

    def get_active_timesheets(self):
        try:
            r = self.session.get(self._url("timesheets/active"), timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(f"Aktive Timesheets laden fehlgeschlagen: {e}")
            return []

    def start_timesheet(self, project_id, activity_id):
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        payload = {
            "begin": now,
            "project": project_id,
            "activity": activity_id,
        }
        try:
            r = self.session.post(self._url("timesheets"), json=payload, timeout=10)
            r.raise_for_status()
            data = r.json()
            log.info(f"Timesheet gestartet: ID={data.get('id')}")
            return data
        except Exception as e:
            log.error(f"Timesheet starten fehlgeschlagen: {e}")
            return None

    def stop_timesheet(self, timesheet_id):
        try:
            r = self.session.patch(self._url(f"timesheets/{timesheet_id}/stop"), timeout=10)
            r.raise_for_status()
            data = r.json()
            log.info(f"Timesheet gestoppt: ID={timesheet_id}")
            return data
        except Exception as e:
            log.error(f"Timesheet stoppen fehlgeschlagen: {e}")
            return None

    def restart_timesheet(self, timesheet_id):
        try:
            r = self.session.patch(self._url(f"timesheets/{timesheet_id}/restart"), timeout=10)
            r.raise_for_status()
            data = r.json()
            log.info(f"Timesheet neu gestartet: ID={data.get('id')}")
            return data
        except Exception as e:
            log.error(f"Timesheet Restart fehlgeschlagen: {e}")
            return None

    def update_timesheet(self, timesheet_id, project_id, activity_id):
        """Stop current and start new with different project/activity."""
        self.stop_timesheet(timesheet_id)
        return self.start_timesheet(project_id, activity_id)


# ========== Idle Monitor (Wayland/GNOME via DBus) ==========
class IdleMonitor:
    """Uses org.gnome.Mutter.IdleMonitor over D-Bus for Wayland-compatible idle detection."""

    def __init__(self):
        self._bus = None
        self._proxy = None
        self._connect()

    def _connect(self):
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self._proxy = Gio.DBusProxy.new_sync(
                self._bus,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.gnome.Mutter.IdleMonitor",
                "/org/gnome/Mutter/IdleMonitor/Core",
                "org.gnome.Mutter.IdleMonitor",
                None,
            )
            log.info("IdleMonitor D-Bus Verbindung hergestellt.")
        except Exception as e:
            log.error(f"IdleMonitor D-Bus Verbindung fehlgeschlagen: {e}")
            self._proxy = None

    def get_idle_time_ms(self):
        """Returns idle time in milliseconds, or -1 on error."""
        if not self._proxy:
            self._connect()
            if not self._proxy:
                return -1
        try:
            result = self._proxy.call_sync(
                "GetIdletime",
                None,
                Gio.DBusCallFlags.NONE,
                1000,
                None,
            )
            return result.unpack()[0]
        except Exception as e:
            log.warning(f"GetIdletime fehlgeschlagen: {e}")
            return -1


# ========== Tracking Engine ==========
class TrackingEngine:
    def __init__(self, app):
        self.app = app
        self.config = load_config()
        self.state = TrackingState.STOPPED
        self.current_timesheet_id = None
        self.idle_monitor = IdleMonitor()
        self.kimai = None
        self._running = False
        self._thread = None
        self._rebuild_client()

    def _rebuild_client(self):
        if self.config.get("kimai_url") and self.config.get("api_token"):
            self.kimai = KimaiClient(self.config["kimai_url"], self.config["api_token"])
        else:
            self.kimai = None

    def update_config(self, config):
        self.config = config
        save_config(config)
        self._rebuild_client()

    def start_monitoring(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        log.info("Überwachung gestartet.")

    def stop_monitoring(self):
        self._running = False
        if self.state == TrackingState.TRACKING and self.current_timesheet_id:
            self._stop_tracking()
        log.info("Überwachung gestoppt.")

    def _monitor_loop(self):
        while self._running:
            try:
                self._check_activity()
            except Exception as e:
                log.error(f"Fehler im Überwachungsloop: {e}")
            time.sleep(self.config.get("poll_interval_seconds", 15))

    def _check_activity(self):
        if not self.kimai:
            return

        idle_ms = self.idle_monitor.get_idle_time_ms()
        if idle_ms < 0:
            return

        idle_minutes = idle_ms / 60000.0
        timeout = self.config.get("idle_timeout_minutes", 10)

        if self.state == TrackingState.STOPPED:
            if idle_minutes < 1:
                self._start_tracking()

        elif self.state == TrackingState.TRACKING:
            if idle_minutes >= timeout:
                self._pause_tracking()

        elif self.state == TrackingState.PAUSED:
            if idle_minutes < 1:
                self._resume_tracking()

    def _start_tracking(self):
        project_id = self.config.get("default_project_id")
        activity_id = self.config.get("default_activity_id")
        if not project_id or not activity_id:
            log.warning("Kein Standard-Projekt/Aktivität konfiguriert.")
            return

        # Check if there's already an active timesheet
        active = self.kimai.get_active_timesheets()
        if active:
            self.current_timesheet_id = active[0].get("id")
            self.state = TrackingState.TRACKING
            log.info(f"Bestehendes aktives Timesheet gefunden: ID={self.current_timesheet_id}")
            GLib.idle_add(self.app.on_tracking_started, False)
            return

        result = self.kimai.start_timesheet(project_id, activity_id)
        if result:
            self.current_timesheet_id = result.get("id")
            self.state = TrackingState.TRACKING
            GLib.idle_add(self.app.on_tracking_started, True)

    def _pause_tracking(self):
        if self.current_timesheet_id:
            result = self.kimai.stop_timesheet(self.current_timesheet_id)
            if result:
                self.state = TrackingState.PAUSED
                GLib.idle_add(self.app.on_tracking_paused)

    def _stop_tracking(self):
        if self.current_timesheet_id:
            self.kimai.stop_timesheet(self.current_timesheet_id)
        self.state = TrackingState.STOPPED
        self.current_timesheet_id = None

    def _resume_tracking(self):
        project_id = self.config.get("default_project_id")
        activity_id = self.config.get("default_activity_id")
        if not project_id or not activity_id:
            return

        result = self.kimai.start_timesheet(project_id, activity_id)
        if result:
            self.current_timesheet_id = result.get("id")
            self.state = TrackingState.TRACKING
            GLib.idle_add(self.app.on_tracking_resumed)

    def switch_project_activity(self, project_id, activity_id):
        """Switch to a different project/activity for the current tracking."""
        if self.state == TrackingState.TRACKING and self.current_timesheet_id:
            result = self.kimai.update_timesheet(self.current_timesheet_id, project_id, activity_id)
            if result:
                self.current_timesheet_id = result.get("id")
                self.config["default_project_id"] = project_id
                self.config["default_activity_id"] = activity_id
                return True
        return False


# ========== Quick Switch Dialog ==========
class QuickSwitchDialog(Adw.Window):
    def __init__(self, app, engine, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.engine = engine
        self.set_title("Projekt / Aufgabe ändern")
        self.set_default_size(420, 350)
        self.set_modal(True)
        if app.main_window:
            self.set_transient_for(app.main_window)

        self._projects = []
        self._activities = []

        # Build UI
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_content(box)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        box.append(header)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(500)
        clamp.set_margin_top(20)
        clamp.set_margin_bottom(20)
        clamp.set_margin_start(20)
        clamp.set_margin_end(20)
        box.append(clamp)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        clamp.set_child(content)

        # Info label
        info = Gtk.Label(label="Wähle ein anderes Projekt und eine Aufgabe für die laufende Zeiterfassung:")
        info.set_wrap(True)
        info.set_xalign(0)
        content.append(info)

        # Project dropdown
        prj_label = Gtk.Label(label="Projekt")
        prj_label.set_xalign(0)
        prj_label.add_css_class("heading")
        content.append(prj_label)

        self.project_dropdown = Gtk.DropDown()
        content.append(self.project_dropdown)

        # Activity dropdown
        act_label = Gtk.Label(label="Aufgabe / Aktivität")
        act_label.set_xalign(0)
        act_label.add_css_class("heading")
        content.append(act_label)

        self.activity_dropdown = Gtk.DropDown()
        content.append(self.activity_dropdown)

        # Button
        btn = Gtk.Button(label="Übernehmen")
        btn.add_css_class("suggested-action")
        btn.set_margin_top(12)
        btn.connect("clicked", self._on_apply)
        content.append(btn)

        # Spinner
        self.spinner = Gtk.Spinner()
        content.append(self.spinner)

        # Load data in background
        self.spinner.start()
        threading.Thread(target=self._load_data, daemon=True).start()

    def _load_data(self):
        if not self.engine.kimai:
            GLib.idle_add(self.spinner.stop)
            return

        self._projects = self.engine.kimai.get_projects()
        GLib.idle_add(self._populate_projects)

    def _populate_projects(self):
        names = [p.get("name", "?") for p in self._projects]
        model = Gtk.StringList.new(names)
        self.project_dropdown.set_model(model)

        # Pre-select current project
        current_pid = self.engine.config.get("default_project_id")
        for i, p in enumerate(self._projects):
            if p.get("id") == current_pid:
                self.project_dropdown.set_selected(i)
                break

        self.project_dropdown.connect("notify::selected", self._on_project_changed)
        self._on_project_changed(None, None)
        self.spinner.stop()

    def _on_project_changed(self, widget, pspec):
        idx = self.project_dropdown.get_selected()
        if idx < len(self._projects):
            pid = self._projects[idx].get("id")
            threading.Thread(target=self._load_activities, args=(pid,), daemon=True).start()

    def _load_activities(self, project_id):
        self._activities = self.engine.kimai.get_activities(project_id)
        # Also add global activities
        global_acts = self.engine.kimai.get_activities(None)
        seen_ids = {a["id"] for a in self._activities}
        for a in global_acts:
            if a["id"] not in seen_ids:
                self._activities.append(a)
        GLib.idle_add(self._populate_activities)

    def _populate_activities(self):
        names = [a.get("name", "?") for a in self._activities]
        model = Gtk.StringList.new(names)
        self.activity_dropdown.set_model(model)

        current_aid = self.engine.config.get("default_activity_id")
        for i, a in enumerate(self._activities):
            if a.get("id") == current_aid:
                self.activity_dropdown.set_selected(i)
                break

    def _on_apply(self, btn):
        pidx = self.project_dropdown.get_selected()
        aidx = self.activity_dropdown.get_selected()

        if pidx < len(self._projects) and aidx < len(self._activities):
            project_id = self._projects[pidx]["id"]
            activity_id = self._activities[aidx]["id"]
            project_name = self._projects[pidx].get("name", "?")
            activity_name = self._activities[aidx].get("name", "?")

            def do_switch():
                success = self.engine.switch_project_activity(project_id, activity_id)
                GLib.idle_add(self._switch_done, success, project_name, activity_name)

            threading.Thread(target=do_switch, daemon=True).start()

    def _switch_done(self, success, project_name, activity_name):
        if success:
            self.app.send_notification_message(
                "Projekt gewechselt",
                f"Erfasse jetzt: {project_name} → {activity_name}"
            )
        self.close()


# ========== Settings Window ==========
class SettingsWindow(Adw.PreferencesWindow):
    def __init__(self, app, engine, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.engine = engine
        self.set_title(f"{APP_NAME} – Einstellungen")
        self.set_default_size(600, 700)

        self._projects = []
        self._activities = []

        # --- Connection Page ---
        page_conn = Adw.PreferencesPage()
        page_conn.set_title("Verbindung")
        page_conn.set_icon_name("network-server-symbolic")
        self.add(page_conn)

        group_kimai = Adw.PreferencesGroup()
        group_kimai.set_title("Kimai Verbindung")
        group_kimai.set_description("Gib die URL deiner Kimai-Instanz und deinen API-Token ein.")
        page_conn.add(group_kimai)

        self.url_row = Adw.EntryRow()
        self.url_row.set_title("Kimai URL")
        self.url_row.set_text(self.engine.config.get("kimai_url", ""))
        group_kimai.add(self.url_row)

        self.token_row = Adw.PasswordEntryRow()
        self.token_row.set_title("API Token")
        self.token_row.set_text(self.engine.config.get("api_token", ""))
        group_kimai.add(self.token_row)

        test_btn = Gtk.Button(label="Verbindung testen")
        test_btn.add_css_class("suggested-action")
        test_btn.set_margin_top(8)
        test_btn.connect("clicked", self._on_test_connection)
        group_kimai.add(test_btn)

        self.conn_status = Gtk.Label(label="")
        self.conn_status.set_margin_top(4)
        group_kimai.add(self.conn_status)

        # --- Tracking Page ---
        page_track = Adw.PreferencesPage()
        page_track.set_title("Zeiterfassung")
        page_track.set_icon_name("document-open-recent-symbolic")
        self.add(page_track)

        group_idle = Adw.PreferencesGroup()
        group_idle.set_title("Inaktivitätserkennung")
        page_track.add(group_idle)

        self.idle_spin = Adw.SpinRow.new_with_range(1, 60, 1)
        self.idle_spin.set_title("Inaktivitäts-Timeout (Minuten)")
        self.idle_spin.set_value(self.engine.config.get("idle_timeout_minutes", 10))
        group_idle.add(self.idle_spin)

        self.poll_spin = Adw.SpinRow.new_with_range(5, 120, 5)
        self.poll_spin.set_title("Prüfintervall (Sekunden)")
        self.poll_spin.set_value(self.engine.config.get("poll_interval_seconds", 15))
        group_idle.add(self.poll_spin)

        # Default project/activity
        group_default = Adw.PreferencesGroup()
        group_default.set_title("Standard Projekt & Aufgabe")
        group_default.set_description("Wird automatisch verwendet wenn die Zeiterfassung startet.")
        page_track.add(group_default)

        self.project_dropdown = Gtk.DropDown()
        prj_row = Adw.ActionRow()
        prj_row.set_title("Projekt")
        prj_row.add_suffix(self.project_dropdown)
        group_default.add(prj_row)

        self.activity_dropdown = Gtk.DropDown()
        act_row = Adw.ActionRow()
        act_row.set_title("Aufgabe / Aktivität")
        act_row.add_suffix(self.activity_dropdown)
        group_default.add(act_row)

        load_btn = Gtk.Button(label="Projekte & Aufgaben laden")
        load_btn.set_margin_top(8)
        load_btn.connect("clicked", self._on_load_projects)
        group_default.add(load_btn)

        # --- System Page ---
        page_sys = Adw.PreferencesPage()
        page_sys.set_title("System")
        page_sys.set_icon_name("emblem-system-symbolic")
        self.add(page_sys)

        group_auto = Adw.PreferencesGroup()
        group_auto.set_title("Autostart")
        page_sys.add(group_auto)

        self.autostart_switch = Adw.SwitchRow()
        self.autostart_switch.set_title("Beim Systemstart automatisch starten")
        self.autostart_switch.set_active(self.engine.config.get("autostart", False))
        group_auto.add(self.autostart_switch)

        # Save button
        group_save = Adw.PreferencesGroup()
        page_sys.add(group_save)
        save_btn = Gtk.Button(label="Einstellungen speichern")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save)
        group_save.add(save_btn)

    def _on_test_connection(self, btn):
        url = self.url_row.get_text().strip()
        token = self.token_row.get_text().strip()
        if not url or not token:
            self.conn_status.set_text("⚠ Bitte URL und Token eingeben.")
            return

        self.conn_status.set_text("Teste Verbindung …")

        def test():
            client = KimaiClient(url, token)
            ok = client.test_connection()
            GLib.idle_add(self._show_conn_result, ok)

        threading.Thread(target=test, daemon=True).start()

    def _show_conn_result(self, ok):
        if ok:
            self.conn_status.set_text("✓ Verbindung erfolgreich!")
        else:
            self.conn_status.set_text("✗ Verbindung fehlgeschlagen. Prüfe URL und Token.")

    def _on_load_projects(self, btn):
        url = self.url_row.get_text().strip()
        token = self.token_row.get_text().strip()
        if not url or not token:
            return

        def load():
            client = KimaiClient(url, token)
            self._projects = client.get_projects()
            GLib.idle_add(self._populate_projects)

        threading.Thread(target=load, daemon=True).start()

    def _populate_projects(self):
        names = [p.get("name", "?") for p in self._projects]
        model = Gtk.StringList.new(names)
        self.project_dropdown.set_model(model)

        current_pid = self.engine.config.get("default_project_id")
        for i, p in enumerate(self._projects):
            if p.get("id") == current_pid:
                self.project_dropdown.set_selected(i)
                break

        self.project_dropdown.connect("notify::selected", self._on_project_selected)
        self._on_project_selected(None, None)

    def _on_project_selected(self, widget, pspec):
        idx = self.project_dropdown.get_selected()
        if idx < len(self._projects):
            pid = self._projects[idx].get("id")
            url = self.url_row.get_text().strip()
            token = self.token_row.get_text().strip()

            def load():
                client = KimaiClient(url, token)
                self._activities = client.get_activities(pid)
                global_acts = client.get_activities(None)
                seen_ids = {a["id"] for a in self._activities}
                for a in global_acts:
                    if a["id"] not in seen_ids:
                        self._activities.append(a)
                GLib.idle_add(self._populate_activities)

            threading.Thread(target=load, daemon=True).start()

    def _populate_activities(self):
        names = [a.get("name", "?") for a in self._activities]
        model = Gtk.StringList.new(names)
        self.activity_dropdown.set_model(model)

        current_aid = self.engine.config.get("default_activity_id")
        for i, a in enumerate(self._activities):
            if a.get("id") == current_aid:
                self.activity_dropdown.set_selected(i)
                break

    def _on_save(self, btn):
        config = dict(self.engine.config)
        config["kimai_url"] = self.url_row.get_text().strip()
        config["api_token"] = self.token_row.get_text().strip()
        config["idle_timeout_minutes"] = int(self.idle_spin.get_value())
        config["poll_interval_seconds"] = int(self.poll_spin.get_value())
        config["autostart"] = self.autostart_switch.get_active()

        pidx = self.project_dropdown.get_selected()
        if pidx is not None and pidx < len(self._projects):
            config["default_project_id"] = self._projects[pidx]["id"]

        aidx = self.activity_dropdown.get_selected()
        if aidx is not None and aidx < len(self._activities):
            config["default_activity_id"] = self._activities[aidx]["id"]

        self.engine.update_config(config)
        manage_autostart(config.get("autostart", False))

        self.app.send_notification_message("Einstellungen gespeichert", "Die Konfiguration wurde aktualisiert.")
        self.close()


# ========== Autostart Management ==========
def manage_autostart(enable):
    AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
    desktop_content = f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Comment=Automatische Kimai Zeiterfassung
Exec={sys.executable} {Path(__file__).resolve()} --background
Icon=document-open-recent
Terminal=false
Categories=Utility;
X-GNOME-Autostart-enabled={'true' if enable else 'false'}
StartupNotify=false
"""
    if enable:
        with open(AUTOSTART_FILE, "w") as f:
            f.write(desktop_content)
        log.info("Autostart aktiviert.")
    else:
        if AUTOSTART_FILE.exists():
            AUTOSTART_FILE.unlink()
            log.info("Autostart deaktiviert.")


# ========== Main Window ==========
class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app, engine, **kwargs):
        super().__init__(application=app, **kwargs)
        self.app = app
        self.engine = engine
        self.set_title(APP_NAME)
        self.set_default_size(480, 500)

        # Main layout
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_content(main_box)

        # Header bar
        header = Adw.HeaderBar()
        main_box.append(header)

        # Settings button
        settings_btn = Gtk.Button(icon_name="emblem-system-symbolic")
        settings_btn.set_tooltip_text("Einstellungen")
        settings_btn.connect("clicked", self._on_settings)
        header.pack_end(settings_btn)

        # Content
        clamp = Adw.Clamp()
        clamp.set_maximum_size(500)
        clamp.set_margin_top(24)
        clamp.set_margin_bottom(24)
        clamp.set_margin_start(24)
        clamp.set_margin_end(24)
        main_box.append(clamp)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        clamp.set_child(content)

        # Status card
        status_group = Adw.PreferencesGroup()
        status_group.set_title("Status")
        content.append(status_group)

        self.status_row = Adw.ActionRow()
        self.status_row.set_title("Zeiterfassung")
        self.status_row.set_subtitle("Gestoppt")
        self.status_icon = Gtk.Image.new_from_icon_name("media-record-symbolic")
        self.status_row.add_prefix(self.status_icon)
        status_group.add(self.status_row)

        self.project_row = Adw.ActionRow()
        self.project_row.set_title("Projekt")
        self.project_row.set_subtitle("–")
        status_group.add(self.project_row)

        self.activity_row = Adw.ActionRow()
        self.activity_row.set_title("Aufgabe")
        self.activity_row.set_subtitle("–")
        status_group.add(self.activity_row)

        # Controls
        control_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        control_box.set_halign(Gtk.Align.CENTER)
        content.append(control_box)

        self.start_btn = Gtk.Button(label="Überwachung starten")
        self.start_btn.add_css_class("suggested-action")
        self.start_btn.add_css_class("pill")
        self.start_btn.connect("clicked", self._on_start)
        control_box.append(self.start_btn)

        self.stop_btn = Gtk.Button(label="Überwachung stoppen")
        self.stop_btn.add_css_class("destructive-action")
        self.stop_btn.add_css_class("pill")
        self.stop_btn.set_sensitive(False)
        self.stop_btn.connect("clicked", self._on_stop)
        control_box.append(self.stop_btn)

        switch_btn = Gtk.Button(label="Projekt wechseln")
        switch_btn.add_css_class("pill")
        switch_btn.connect("clicked", self._on_switch)
        control_box.append(switch_btn)

        # Connection info
        info_group = Adw.PreferencesGroup()
        content.append(info_group)

        self.conn_row = Adw.ActionRow()
        self.conn_row.set_title("Kimai")
        self.conn_row.set_subtitle("Nicht verbunden")
        info_group.add(self.conn_row)

        self._update_display()

        # Check connection on startup
        if self.engine.kimai:
            threading.Thread(target=self._check_initial_connection, daemon=True).start()

    def _check_initial_connection(self):
        ok = self.engine.kimai.test_connection()
        GLib.idle_add(self._set_connection_status, ok)

    def _set_connection_status(self, ok):
        if ok:
            self.conn_row.set_subtitle(f"Verbunden mit {self.engine.config.get('kimai_url', '')}")
        else:
            self.conn_row.set_subtitle("Verbindung fehlgeschlagen")

    def _update_display(self):
        state = self.engine.state
        if state == TrackingState.TRACKING:
            self.status_row.set_subtitle("Aktiv – Zeiterfassung läuft")
            self.status_icon.set_from_icon_name("media-record-symbolic")
        elif state == TrackingState.PAUSED:
            self.status_row.set_subtitle("Pausiert – Warte auf Aktivität")
            self.status_icon.set_from_icon_name("media-playback-pause-symbolic")
        else:
            self.status_row.set_subtitle("Gestoppt")
            self.status_icon.set_from_icon_name("media-playback-stop-symbolic")

    def update_status(self, state_text, project_name=None, activity_name=None):
        self.status_row.set_subtitle(state_text)
        if project_name:
            self.project_row.set_subtitle(project_name)
        if activity_name:
            self.activity_row.set_subtitle(activity_name)

    def _on_start(self, btn):
        if not self.engine.kimai:
            dialog = Adw.AlertDialog()
            dialog.set_heading("Keine Verbindung")
            dialog.set_body("Bitte konfiguriere zuerst die Kimai-Verbindung in den Einstellungen.")
            dialog.add_response("ok", "OK")
            dialog.present(self)
            return

        if not self.engine.config.get("default_project_id") or not self.engine.config.get("default_activity_id"):
            dialog = Adw.AlertDialog()
            dialog.set_heading("Kein Standard-Projekt")
            dialog.set_body("Bitte wähle zuerst ein Standard-Projekt und eine Aufgabe in den Einstellungen.")
            dialog.add_response("ok", "OK")
            dialog.present(self)
            return

        self.engine.start_monitoring()
        self.start_btn.set_sensitive(False)
        self.stop_btn.set_sensitive(True)
        self.update_status("Überwachung aktiv – Warte auf Aktivität …")

    def _on_stop(self, btn):
        self.engine.stop_monitoring()
        self.start_btn.set_sensitive(True)
        self.stop_btn.set_sensitive(False)
        self.update_status("Gestoppt")
        self.project_row.set_subtitle("–")
        self.activity_row.set_subtitle("–")

    def _on_switch(self, btn):
        dialog = QuickSwitchDialog(self.app, self.engine)
        dialog.present()

    def _on_settings(self, btn):
        win = SettingsWindow(self.app, self.engine)
        win.present()


# ========== Application ==========
class KimaiTrackerApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.engine = None
        self.main_window = None
        self._background = "--background" in sys.argv

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.engine = TrackingEngine(self)

    def do_activate(self):
        if not self.main_window:
            self.main_window = MainWindow(self, self.engine)

        if self._background:
            # Start monitoring immediately in background mode
            if self.engine.kimai and self.engine.config.get("default_project_id"):
                self.engine.start_monitoring()
                log.info("Hintergrundmodus: Überwachung gestartet.")
            # Don't show the window, but keep app running
            # Show the window if user re-activates
            self.main_window.present()
            self._background = False
        else:
            self.main_window.present()

    def on_tracking_started(self, is_new):
        """Called from engine when tracking starts (on GTK main thread)."""
        project_name = "?"
        activity_name = "?"

        # Try to get names from cache
        if self.engine.kimai:
            projects = self.engine.kimai.get_projects()
            for p in projects:
                if p.get("id") == self.engine.config.get("default_project_id"):
                    project_name = p.get("name", "?")
                    break
            activities = self.engine.kimai.get_activities(self.engine.config.get("default_project_id"))
            for a in activities:
                if a.get("id") == self.engine.config.get("default_activity_id"):
                    activity_name = a.get("name", "?")
                    break

        if self.main_window:
            self.main_window.update_status(
                "Aktiv – Zeiterfassung läuft",
                project_name,
                activity_name,
            )

        if is_new:
            self._send_tracking_notification(project_name, activity_name)

    def on_tracking_paused(self):
        """Called when tracking is paused due to inactivity."""
        if self.main_window:
            self.main_window.update_status("Pausiert – Warte auf Aktivität")
        self.send_notification_message(
            "Zeiterfassung pausiert",
            "Inaktivität erkannt. Die Erfassung wird bei Rückkehr fortgesetzt."
        )

    def on_tracking_resumed(self):
        """Called when tracking resumes after user returns."""
        if self.main_window:
            self.main_window.update_status("Aktiv – Zeiterfassung läuft")
        self.send_notification_message(
            "Zeiterfassung fortgesetzt",
            "Willkommen zurück! Die Erfassung läuft weiter."
        )

    def _send_tracking_notification(self, project_name, activity_name):
        """Send a notification with action to change project/activity."""
        notification = Gio.Notification.new("Zeiterfassung gestartet")
        notification.set_body(f"Projekt: {project_name}\nAufgabe: {activity_name}\n\nKlicke um zu ändern.")
        notification.set_default_action("app.show-quick-switch")
        notification.set_priority(Gio.NotificationPriority.HIGH)
        self.send_notification("tracking-started", notification)

        # Register action
        action = Gio.SimpleAction.new("show-quick-switch", None)
        action.connect("activate", self._on_notification_clicked)
        self.add_action(action)

    def _on_notification_clicked(self, action, param):
        """Open quick switch dialog when notification is clicked."""
        if self.main_window:
            self.main_window.present()
        dialog = QuickSwitchDialog(self, self.engine)
        dialog.present()

    def send_notification_message(self, title, body):
        notification = Gio.Notification.new(title)
        notification.set_body(body)
        self.send_notification(None, notification)


# ========== Entry Point ==========
def main():
    app = KimaiTrackerApp()
    app.run(sys.argv)


if __name__ == "__main__":
    main()
