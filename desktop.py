"""The desktop: wallpaper behind all windows, with a right-click menu."""
import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

from launcher import menu_item, new_menu, run  # noqa: E402
from taskbar import CONFIG_DIR  # noqa: E402

WALLPAPER_FILE = os.path.join(CONFIG_DIR, "wallpaper")


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
        try:
            with open(WALLPAPER_FILE) as f:
                self.set_wallpaper(f.read().strip())
        except OSError:
            pass  # no wallpaper yet: the plain background colour

    def set_wallpaper(self, path):
        try:
            self.image.set_from_pixbuf(cover(path, *self.size))
        except GLib.Error:
            self.image.clear()

    def _menu(self, ev):
        self.menu = new_menu()
        for entry in (("Open terminal", lambda: run("x-terminal-emulator")),
                      ("File manager", lambda: run("thunar", os.path.expanduser("~"))),
                      None,
                      ("Change wallpaper…", self._choose_wallpaper),
                      ("Settings", lambda: run("xfce4-settings-manager"))):
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

    def _choose_wallpaper(self):
        dialog = Gtk.FileChooserNative(title="Choose a wallpaper", action=Gtk.FileChooserAction.OPEN)
        images = Gtk.FileFilter()
        images.set_name("Images")
        images.add_pixbuf_formats()
        dialog.add_filter(images)
        dialog.set_current_folder(os.path.expanduser("~/Pictures"))
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            path = dialog.get_filename()
            self.set_wallpaper(path)
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(WALLPAPER_FILE, "w") as f:
                f.write(path + "\n")
        dialog.destroy()
