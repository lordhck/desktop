"""Volume icon in the tray (through pactl): scroll to change, click for a slider."""
import os
import re
import signal
import subprocess

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

import network  # noqa: E402
from launcher import settings_menu  # noqa: E402
from network import ICON, css, image, pix  # noqa: E402

SINK = "@DEFAULT_SINK@"
STEP = 5


def pactl(*args, done=None):
    proc = Gio.Subprocess.new(["pactl", *args], Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
    proc.communicate_utf8_async(None, None, lambda p, r: done and done(p.communicate_utf8_finish(r)[1] or ""))


def icon_name(volume, muted):
    return "volume-mute" if muted or volume == 0 else f"volume-{1 if volume < 50 else 2}"


class Volume:
    """Volume and mute of the default output, kept in sync through `pactl subscribe`;
    on_change() runs after every update."""

    def __init__(self, on_change):
        self.volume, self.muted, self.on_change = 0, False, on_change
        self.refresh()
        self._subscribe()

    @property
    def shown(self):
        # muted reads as 0; pulse keeps the real volume for unmuting
        return 0 if self.muted else self.volume

    def _subscribe(self):
        # pactl reports every change (keys, other apps), so no polling;
        # it ignores a closed pipe, so pdeathsig ends it with our process
        proc = Gio.Subprocess.new(["setpriv", "--pdeathsig", "TERM", "pactl", "subscribe"],
                                  Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        stream = Gio.DataInputStream.new(proc.get_stdout_pipe())

        def line(s, result):
            text, _ = s.read_line_finish_utf8(result)
            if text is None:  # sound server restarted
                GLib.timeout_add_seconds(2, lambda: self._subscribe() and False)
                return
            if " on sink " in text or " on server " in text:
                self.refresh()
            s.read_line_async(GLib.PRIORITY_DEFAULT, None, line)
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, line)

    def refresh(self):
        def got_volume(out):
            m = re.search(r"(\d+)%", out)
            self.volume = int(m.group(1)) if m else 0
            pactl("get-sink-mute", SINK, done=got_mute)

        def got_mute(out):
            self.muted = "yes" in out
            self.on_change()
        pactl("get-sink-volume", SINK, done=got_volume)

    def set_volume(self, volume):
        if self.muted:
            pactl("set-sink-mute", SINK, "0")
        pactl("set-sink-volume", SINK, f"{max(0, min(100, volume))}%")

    def toggle_mute(self):
        pactl("set-sink-mute", SINK, "toggle")


class VolumeRow(Gtk.Box):
    """Mute button, slider and percentage; in the tray popup and in the Control Panel."""

    def __init__(self, vol):
        super().__init__(spacing=10)
        self.vol = vol
        css(self, "volume-row")
        self.mute = Gtk.Button(tooltip_text="Mute")
        self.mute.connect("clicked", lambda *_: vol.toggle_mute())
        self.add(self.mute)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale_handler = self.scale.connect("value-changed", lambda s: vol.set_volume(int(s.get_value())))
        self.add(self.scale)
        self.percent = network.label("", "dim", width_chars=4, xalign=1)
        self.add(self.percent)
        self.refresh()

    def refresh(self):
        vol = self.vol
        if self.mute.get_child():
            self.mute.get_child().destroy()
        self.mute.add(image(icon_name(vol.volume, vol.muted), 18))
        self.mute.show_all()
        # don't echo our own update back to pactl
        with self.scale.handler_block(self.scale_handler):
            self.scale.set_value(vol.shown)
        self.percent.set_text(f"{vol.shown}%")


class VolItem(Gtk.Button):
    """Tray icon: scroll to change, click for the popup."""

    def __init__(self):
        super().__init__(relief=Gtk.ReliefStyle.NONE)
        self.get_style_context().add_class("tray-item")
        self.image = Gtk.Image()
        self.add(self.image)
        self.popup = None
        self.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.connect("scroll-event", self._on_scroll)
        self.connect("clicked", lambda *_: self.popup or Popup(self))
        settings_menu(self, "Sound settings…", "sound")
        # --reload execs in place, which keeps the old subscriber as our child
        stale = subprocess.run(["pgrep", "-P", str(os.getpid()), "-x", "pactl"], capture_output=True, text=True)
        for pid in map(int, stale.stdout.split()):
            os.kill(pid, signal.SIGTERM)
            os.waitpid(pid, 0)
        self.vol = Volume(self._changed)

    def _changed(self):
        vol = self.vol
        self.image.set_from_pixbuf(pix(icon_name(vol.volume, vol.muted), ICON))
        self.set_tooltip_text(f"Volume: {'muted' if vol.muted else f'{vol.volume}%'}")
        if self.popup:
            self.popup.row.refresh()

    def _on_scroll(self, _w, ev):
        if ev.direction == Gdk.ScrollDirection.SMOOTH:
            dy = ev.delta_y
        else:
            dy = {Gdk.ScrollDirection.UP: -1, Gdk.ScrollDirection.DOWN: 1}.get(ev.direction, 0)
        if dy:
            self.vol.set_volume(self.vol.shown - STEP if dy > 0 else self.vol.shown + STEP)
        return True


class Popup(Gtk.Window):
    """Small box above the tray icon with a VolumeRow."""

    # same placement and grab behaviour as the network popup
    _place = network.Popup._place
    _grab = network.Popup._grab
    _on_button = network.Popup._on_button

    def __init__(self, item):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.item = item
        item.popup = self
        css(self, "network", "volume")
        self.row = VolumeRow(item.vol)
        self.add(self.row)

        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("key-press-event", lambda _w, ev: ev.keyval == Gdk.KEY_Escape and (self.destroy() or True))
        self.connect("button-press-event", self._on_button)
        self.connect("map-event", lambda *_: GLib.timeout_add(30, self._grab, 20))
        self.connect("destroy", self._on_destroy)

        self.row.show_all()
        self.realize()
        self._place()
        self.show()

    def _on_destroy(self, *_):
        self.grab_remove()
        Gdk.Display.get_default().get_default_seat().ungrab()
        self.item.popup = None
