"""Notification area: status items and the clock, at the right end of the taskbar."""
import html
import os
import re
import shlex
import shutil
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

ICON = 20
SCRIPT_PERIOD = 3  # seconds between runs of a status script


def find_netmon():
    found = shutil.which("netmon")
    if found:
        return found
    dev = os.path.expanduser("~/dev/netmon/netmon.py")
    return dev if os.path.exists(dev) else None


class ScriptItem(Gtk.Button):
    """A tray icon driven by a script printing Generic Monitor tags
    (<img>, <tool>, <click>), e.g. netmon."""

    def __init__(self, command):
        super().__init__(relief=Gtk.ReliefStyle.NONE)
        self.command = command
        self.click = None
        self._last_img = None
        self.get_style_context().add_class("tray-item")
        self.image = Gtk.Image()
        self.add(self.image)
        self.connect("clicked", lambda *_: self._on_click())
        self._run()
        GLib.timeout_add_seconds(SCRIPT_PERIOD, self._run)

    def _run(self):
        proc = Gio.Subprocess.new([self.command], Gio.SubprocessFlags.STDOUT_PIPE
                                  | Gio.SubprocessFlags.STDERR_SILENCE)
        proc.communicate_utf8_async(None, None, self._on_output)
        return True

    def _on_output(self, proc, result):
        try:
            _ok, out, _err = proc.communicate_utf8_finish(result)
        except GLib.Error:
            return
        tag = lambda name: (m.group(1) if (m := re.search(  # noqa: E731
            f"<{name}>(.*?)</{name}>", out or "", re.S)) else None)
        img, tool, self.click = tag("img"), tag("tool"), tag("click")
        if img and img != self._last_img and os.path.exists(img):
            self._last_img = img
            self.image.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_size(img, ICON, ICON))
        self.set_tooltip_markup(tool or "")

    def _on_click(self):
        if self.click:
            Gio.Subprocess.new(shlex.split(html.unescape(self.click)), Gio.SubprocessFlags.NONE)


class Clock(Gtk.Label):
    """Time on one line; the date shows on hover."""

    def __init__(self):
        super().__init__()
        self.get_style_context().add_class("clock")
        self._tick()

    def _tick(self):
        now = time.localtime()
        self.set_text(time.strftime("%H:%M", now))
        self.set_tooltip_text(time.strftime("%A %-d %B %Y", now))
        GLib.timeout_add_seconds(60 - now.tm_sec, self._tick)  # next minute boundary
        return False


class Tray(Gtk.Box):
    def __init__(self):
        super().__init__()
        self.get_style_context().add_class("tray")
        netmon = find_netmon()
        if netmon:
            self.pack_start(ScriptItem(netmon), False, False, 0)
        self.pack_start(Clock(), False, False, 0)
