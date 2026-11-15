"""Notification area: status items, the clock and show desktop, at the right end of the taskbar."""
import os
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Wnck", "3.0")
from gi.repository import Gio, GLib, Gtk, Wnck  # noqa: E402

from launcher import own_icon  # noqa: E402
from network import NetItem  # noqa: E402
from volume import VolItem  # noqa: E402

ICON = 20
CLOCK_FILE = os.path.join(GLib.get_user_config_dir(), "shell", "clock")  # "12h" or "24h", set in the Control Panel


def clock_format(seconds=False):
    try:
        with open(CLOCK_FILE) as f:
            twelve = f.read().strip() == "12h"
    except OSError:
        twelve = False
    return ("%-I:%M" + (":%S" if seconds else "") + " %p") if twelve else ("%H:%M" + (":%S" if seconds else ""))


class Clock(Gtk.Label):
    """Time on one line; the date shows on hover."""

    def __init__(self):
        super().__init__()
        self.get_style_context().add_class("clock")
        self.monitor = Gio.File.new_for_path(CLOCK_FILE).monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect("changed", lambda *_: self._show())
        self._tick()

    def _show(self):
        time.tzset()  # pick up a new time zone without restarting the shell
        now = time.localtime()
        self.set_text(time.strftime(clock_format(), now))
        self.set_tooltip_text(time.strftime("%A %-d %B %Y", now))
        return now

    def _tick(self):
        now = self._show()
        GLib.timeout_add_seconds(60 - now.tm_sec, self._tick)  # next minute boundary
        return False


class ShowDesktop(Gtk.Button):
    def __init__(self):
        super().__init__(relief=Gtk.ReliefStyle.NONE, tooltip_text="Show desktop")
        self.get_style_context().add_class("tray-item")
        image = Gtk.Image.new_from_gicon(own_icon("desktop"), Gtk.IconSize.BUTTON)
        image.set_pixel_size(ICON)
        self.add(image)
        self.connect("clicked", self._toggle)

    def _toggle(self, _b):
        screen = Wnck.Screen.get_default()
        screen.toggle_showing_desktop(not screen.get_showing_desktop())


class Tray(Gtk.Box):
    def __init__(self):
        super().__init__()
        self.get_style_context().add_class("tray")
        self.pack_start(VolItem(), False, False, 0)
        self.pack_start(NetItem(), False, False, 0)
        self.pack_start(Clock(), False, False, 0)
        self.pack_start(ShowDesktop(), False, False, 0)
