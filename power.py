"""Power options (Start > Power): a box of three buttons in the centre of the screen."""
import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

ICONS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "icons")
ICON = 36


def _logind(action):
    # interactive: lets polkit ask for a password if needed
    Gio.bus_get_sync(Gio.BusType.SYSTEM).call_sync(
        "org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager",
        action, GLib.Variant("(b)", (True,)), None, Gio.DBusCallFlags.NONE, -1, None)


def _logout():
    # through xfce4-session so the session is saved and apps close cleanly
    Gio.Subprocess.new(["xfce4-session-logout", "--logout"], Gio.SubprocessFlags.NONE)


ACTIONS = [
    ("Shut down", "power", lambda: _logind("PowerOff")),
    ("Restart", "restart", lambda: _logind("Reboot")),
    ("Log out", "logout", _logout),
]


class PowerDialog(Gtk.Window):
    def __init__(self):
        super().__init__(type_hint=Gdk.WindowTypeHint.DIALOG, decorated=False,
                         resizable=False, skip_taskbar_hint=True, skip_pager_hint=True,
                         window_position=Gtk.WindowPosition.CENTER_ALWAYS)
        self.set_keep_above(True)
        visual = self.get_screen().get_rgba_visual()
        if visual and self.get_screen().is_composited():  # transparent corners for the rounded box
            self.set_visual(visual)
        self.get_style_context().add_class("power")
        box = Gtk.Box(spacing=12, margin=20)  # GTK3 ignores CSS padding on toplevels
        for text, icon, action in ACTIONS:
            box.pack_start(self._button(text, icon, action), False, False, 0)
        self.add(box)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("map-event", self._grab)
        self.connect("key-press-event", self._on_key)
        self.connect("button-press-event", self._on_click)

    def _grab(self, *_):
        # like a menu: Esc and outside clicks reach us whatever has focus
        Gdk.Display.get_default().get_default_seat().grab(
            self.get_window(), Gdk.SeatCapabilities.ALL, True, None, None, None)

    def _on_key(self, _w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self.destroy()

    def _on_click(self, _w, ev):
        alloc = self.get_allocation()
        if not (0 <= ev.x < alloc.width and 0 <= ev.y < alloc.height):
            self.destroy()

    def _button(self, text, icon, action):
        button = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(os.path.join(ICONS, f"{icon}.svg"), ICON, ICON)
        content.pack_start(Gtk.Image.new_from_pixbuf(pixbuf), False, False, 0)
        content.pack_start(Gtk.Label(label=text), False, False, 0)
        button.add(content)
        button.connect("clicked", lambda *_: (self.destroy(), action()))
        return button


def show():
    # wait for the Start menu to release its grab, or ours fails
    GLib.timeout_add(50, lambda: PowerDialog().show_all())
