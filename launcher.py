"""Start button and its Win98-style cascading app menu."""
import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango  # noqa: E402

import power  # noqa: E402

ICONS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "icons")
TOP_ICON = 22   # category icons
APP_ICON = 16   # app icons in submenus

# freedesktop main categories -> (menu name, icon in icons/cat-*.svg); first match wins
CATEGORIES = [
    ("Utility", "Accessories", "accessories"),
    ("Development", "Development", "development"),
    ("Education", "Education", "education"),
    ("Science", "Education", "education"),
    ("Game", "Games", "games"),
    ("Graphics", "Graphics", "graphics"),
    ("Network", "Internet", "internet"),
    ("AudioVideo", "Multimedia", "multimedia"),
    ("Audio", "Multimedia", "multimedia"),
    ("Video", "Multimedia", "multimedia"),
    ("Office", "Office", "office"),
    ("System", "System", "system"),
]
OTHER = ("Other", "other")
CONTROL_PANEL = os.path.join(os.path.dirname(os.path.realpath(__file__)), "settings.py")


def menu_item(text, icon=None, size=APP_ICON, center=False):
    item = Gtk.MenuItem()
    box = Gtk.Box(spacing=14, halign=Gtk.Align.CENTER if center else Gtk.Align.FILL)
    if icon is not None:
        image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.MENU)
        image.set_pixel_size(size)
        box.pack_start(image, False, False, 0)
    # window titles can be very long
    label = Gtk.Label(label=text, xalign=0, max_width_chars=50, ellipsize=Pango.EllipsizeMode.END)
    box.pack_start(label, not center, not center, 0)
    item.add(box)
    return item


def new_menu():
    menu = Gtk.Menu()
    menu.set_reserve_toggle_size(False)  # no empty checkbox column on the left
    menu.connect("key-press-event", _close_on_shortcut)
    return menu


def _close_on_shortcut(menu, ev):
    """The menu's shortcut closes it too. A Super tap reaches us as Alt+F1 (sent by
    xcape); while open, the menu holds the keyboard, so it arrives here instead of
    re-triggering the shortcut."""
    if not (ev.keyval == Gdk.KEY_F1 and ev.state & Gdk.ModifierType.MOD1_MASK):
        return False
    widget = menu
    while isinstance(widget, Gtk.Menu):  # walk up submenus to the Start button
        attach = widget.get_attach_widget()
        if isinstance(attach, Gtk.ToggleButton):
            attach.set_active(False)
            return True
        widget = attach.get_parent() if attach else None
    menu.popdown()
    return True


def own_icon(name):
    return Gio.FileIcon.new(Gio.File.new_for_path(os.path.join(ICONS, f"{name}.svg")))


def settings_menu(widget, text, page):
    """Right-click menu on a tray icon with one item that opens its Control Panel page."""
    def on_press(_w, ev):
        if ev.button != 3:
            return False
        widget.menu = new_menu()  # kept on the widget, or it's garbage-collected while open
        item = menu_item(text)
        item.connect("activate", lambda *_: run(CONTROL_PANEL, page))
        widget.menu.append(item)
        widget.menu.attach_to_widget(widget, None)
        widget.set_has_tooltip(False)  # it would cover the menu
        widget.menu.connect("deactivate", lambda *_: widget.set_has_tooltip(True))
        widget.menu.show_all()
        widget.menu.popup_at_widget(widget, Gdk.Gravity.NORTH_EAST, Gdk.Gravity.SOUTH_EAST, None)
        return True
    widget.connect("button-press-event", on_press)


def run(*cmd):
    Gio.Subprocess.new(list(cmd), Gio.SubprocessFlags.NONE)


def launch(app):
    app.launch([], Gdk.Display.get_default().get_app_launch_context())


def add_apps(menu, apps):
    for app in sorted(apps, key=lambda a: a.get_display_name().lower()):
        item = menu_item(app.get_display_name(), app.get_icon())
        item.connect("activate", lambda _i, a=app: launch(a))
        menu.append(item)
    return menu


def build_menu():
    """Categories with app submenus, then Settings and Log out."""
    groups, settings = {}, []
    for app in Gio.AppInfo.get_all():
        if not app.should_show():
            continue
        cats = (app.get_categories() or "").split(";")
        if "Settings" in cats:
            settings.append(app)
            continue
        name, icon = next(((n, i) for c, n, i in CATEGORIES if c in cats), OTHER)
        groups.setdefault((name, icon), []).append(app)

    items = []
    for (name, icon), apps in sorted(groups.items()):
        item = menu_item(name, own_icon(f"cat-{icon}"), TOP_ICON)
        item.set_submenu(add_apps(new_menu(), apps))
        items.append(item)

    items.append(Gtk.SeparatorMenuItem())
    item = menu_item("Settings", own_icon("cat-settings"), TOP_ICON)
    sub = new_menu()
    first = menu_item("Control Panel", own_icon("cat-settings"))
    first.connect("activate", lambda *_: run(CONTROL_PANEL))
    sub.append(first)
    if settings:
        sub.append(Gtk.SeparatorMenuItem())
    item.set_submenu(add_apps(sub, settings))
    items.append(item)

    # bottom row: two buttons side by side (menu grid columns are equal width)
    off = menu_item("Power", own_icon("power"), APP_ICON, center=True)
    # same arrow as the submenu items
    arrow = Gtk.Image.new_from_icon_name("pan-end-symbolic", Gtk.IconSize.MENU)
    arrow.set_pixel_size(10)
    arrow.get_style_context().add_class("arrow")
    off.get_child().pack_start(arrow, False, False, 0)
    off.connect("activate", lambda *_: power.show())
    lock = menu_item("Lock", own_icon("lock"), 14, center=True)
    lock.connect("activate", lambda *_: run("xflock4"))
    for item, end in ((off, "first"), (lock, "last")):
        item.get_style_context().add_class("footer")
        item.get_style_context().add_class(end)  # joined like a button group

    menu = new_menu()
    menu.get_style_context().add_class("start-menu")
    for row, item in enumerate(items):
        menu.attach(item, 0, 2, row, row + 1)
    menu.attach(off, 0, 1, len(items), len(items) + 1)
    menu.attach(lock, 1, 2, len(items), len(items) + 1)
    menu.show_all()
    return menu


class StartButton(Gtk.ToggleButton):
    def __init__(self):
        super().__init__(relief=Gtk.ReliefStyle.NONE)
        self.get_style_context().add_class("start")
        self.add(Gtk.Image.new_from_pixbuf(
            GdkPixbuf.Pixbuf.new_from_file_at_size(os.path.join(ICONS, "start.svg"), 24, 24)))
        self.set_tooltip_text("Start")
        self.menu = None
        self._stale = True  # rebuild the menu before the next open
        self._monitor = Gio.AppInfoMonitor.get()  # apps installed/removed
        self._monitor.connect("changed", lambda *_: setattr(self, "_stale", True))
        self.connect("toggled", self._on_toggled)

    def toggle_menu(self):
        """Open/close from outside (Super tap, via xcape + Alt+F1). Short delay: the
        shortcut handler may still hold the keyboard, and the menu needs it."""
        GLib.timeout_add(50, lambda: self.set_active(not self.get_active()) and False)

    def _ready_menu(self):
        if self._stale or self.menu is None:
            if self.menu:
                self.menu.destroy()
            self.menu = build_menu()
            self.menu.attach_to_widget(self, None)
            self.menu.connect("deactivate", lambda *_: self.set_active(False))
            self._stale = False
        return self.menu

    def _on_toggled(self, _b):
        if not self.get_active():
            if self.menu:
                self.menu.popdown()
            return
        self._ready_menu().popup_at_widget(self, Gdk.Gravity.NORTH_WEST,
                                           Gdk.Gravity.SOUTH_WEST, None)
