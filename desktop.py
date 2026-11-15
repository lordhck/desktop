"""The desktop: wallpaper behind all windows, with a right-click menu."""
import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from launcher import CONTROL_PANEL, menu_item, new_menu, run  # noqa: E402
from taskbar import CONFIG_DIR  # noqa: E402

WALLPAPER_FILE = os.path.join(CONFIG_DIR, "wallpaper")


def save_wallpaper(path):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(WALLPAPER_FILE, "w") as f:
        f.write(path + "\n")


def cover(path, width, height):
    """The image scaled to fill width x height, centred and cropped."""
    _, w, h = GdkPixbuf.Pixbuf.get_file_info(path)
    scale = max(width / w, height / h)
    scaled = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, round(w * scale), round(h * scale), False)
    x, y = (scaled.get_width() - width) // 2, (scaled.get_height() - height) // 2
    return scaled.new_subpixbuf(max(x, 0), max(y, 0), min(width, scaled.get_width()),
                                min(height, scaled.get_height()))


class Desktop(Gtk.Window):
    def __init__(self):
        super().__init__(type_hint=Gdk.WindowTypeHint.DESKTOP, decorated=False,
                         skip_taskbar_hint=True, skip_pager_hint=True)
        self.get_style_context().add_class("desktop")
        geo = Gdk.Display.get_default().get_monitor(0).get_geometry()
        self.size = (geo.width, geo.height)
        self.move(geo.x, geo.y)
        self.set_size_request(*self.size)
        self.image = Gtk.Image()
        self.add(self.image)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("button-press-event", lambda _w, ev: ev.button == 3 and self._menu(ev))
        # the Control Panel changes the wallpaper by writing this file
        self.monitor = Gio.File.new_for_path(WALLPAPER_FILE).monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect("changed", lambda _m, _f, _o, event:
                             event == Gio.FileMonitorEvent.CHANGES_DONE_HINT and self.load_wallpaper())
        self.load_wallpaper()

    def load_wallpaper(self):
        try:
            with open(WALLPAPER_FILE) as f:
                self.image.set_from_pixbuf(cover(f.read().strip(), *self.size))
        except (OSError, GLib.Error):
            self.image.clear()  # no wallpaper: the plain background colour

    def _menu(self, ev):
        self.menu = new_menu()
        for entry in (("Open terminal", lambda: run("x-terminal-emulator")),
                      ("File manager", lambda: run("thunar", os.path.expanduser("~"))),
                      None,
                      ("Change wallpaper…", lambda: run(CONTROL_PANEL, "appearance")),
                      ("Settings", lambda: run(CONTROL_PANEL))):
            if entry is None:
                self.menu.append(Gtk.SeparatorMenuItem())
                continue
            text, action = entry
            item = menu_item(text)
            item.connect("activate", lambda _i, a=action: a())
            self.menu.append(item)
        self.menu.attach_to_widget(self, None)
        self.menu.show_all()
        self.menu.popup_at_pointer(ev)
        return True

