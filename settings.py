#!/usr/bin/env python3
"""Control Panel: the shell's own settings app.

    settings.py          open it
    settings.py <page>   open it on a page (appearance, sound, keyboard, startup, about)
"""
import getpass
import glob
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango  # noqa: E402

import volume  # noqa: E402
from desktop import WALLPAPER_FILE, cover, save_wallpaper  # noqa: E402
from network import css, image, label  # noqa: E402
from taskbar import CSS_FILE  # noqa: E402

# (section, [(page, title, subtitle, icon, badge colour, search words)])
SECTIONS = [
    ("You", [
        ("appearance", "Appearance", "Wallpaper", "appearance", "blue", "background desktop picture"),
    ]),
    ("System", [
        ("startup", "Startup", "Apps at login", "startup", "orange", "autostart session login"),
        ("about", "About", "This computer", "about", "grey", "system cpu memory disk version kernel"),
    ]),
    ("Hardware", [
        ("sound", "Sound", "Output and volume", "volume-2", "red", "audio speaker mute"),
        ("network", "Network", "Wi-Fi and Ethernet", "wifi-3", "blue", "wifi internet wireless"),
        ("keyboard", "Keyboard", "Keys and layout", "keyboard", "grey", "shortcuts layout repeat"),
    ]),
    ("Region", [
        ("datetime", "Date & Time", "Clock and time zone", "clock", "teal", "timezone"),
    ]),
]
AUTOSTART_USER = os.path.join(GLib.get_user_config_dir(), "autostart")
AUTOSTART_DIRS = [os.path.join(d, "autostart") for d in reversed(GLib.get_system_config_dirs())] + [AUTOSTART_USER]
DE = "Desktop Entry"
SEARCH_FROM = 15  # a picker with more options than this gets a search box


def card(rows):
    """Rounded box of rows with thin lines between them."""
    box = css(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "card")
    for i, row in enumerate(rows):
        if i:
            box.add(Gtk.Separator())
        box.add(row)
    return box


def row(title, subtitle=None, end=None, icon=None):
    box = css(Gtk.Box(spacing=12), "row")
    if icon:
        box.add(icon)
    texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
    texts.add(label(title))
    if subtitle:
        texts.add(label(subtitle, "dim", ellipsize=Pango.EllipsizeMode.END))
    box.pack_start(texts, True, True, 0)
    if end:
        end.set_valign(Gtk.Align.CENTER)
        box.add(end)
    return box


def page(*children):
    box = css(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "page")
    for child in children:
        box.add(child)
    scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
    scroller.add(box)
    return scroller


def heading(text):
    return label(text.upper(), "section")


def picker(options, current, on_pick):
    """Button with the chosen option; opens a fixed-height scrolling list instead of a
    screen-high menu, with a search box when the list is long. options: [(key, name)]."""
    names = dict(options)
    button = css(Gtk.MenuButton(), "picker")
    content = Gtk.Box(spacing=10)
    chosen = label(names.get(current, current))
    content.pack_start(chosen, True, True, 0)
    content.add(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.MENU))
    button.add(content)

    rows = Gtk.ListBox(activate_on_single_click=True)
    for key, name in options:
        item = Gtk.ListBoxRow()
        item.key = key
        item.add(label(name))
        rows.add(item)
        if key == current:
            rows.select_row(item)
    long = len(options) > SEARCH_FROM
    # long lists keep their height while filtering, so the popover doesn't jump
    scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                  min_content_height=320 if long else -1, max_content_height=320,
                                  min_content_width=260)
    scroller.add(rows)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    popover = css(Gtk.Popover(), "picker-list")
    popover.add(box)
    button.set_popover(popover)

    def picked(_rows, item):
        chosen.set_text(names[item.key])
        on_pick(item.key)
        popover.popdown()

    def opened():
        if long:
            search.set_text("")
            search.grab_focus()
        item = rows.get_selected_row()
        if item:  # centre the current choice
            adj = scroller.get_vadjustment()
            adj.set_value(item.get_allocation().y - (adj.get_page_size() - item.get_allocation().height) / 2)
        return False

    if long:
        search = Gtk.SearchEntry(placeholder_text="Search")
        rows.set_filter_func(lambda item: search.get_text().strip().lower() in names[item.key].lower())
        search.connect("search-changed", lambda *_: rows.invalidate_filter())
        # Enter picks the first match
        search.connect("activate", lambda *_: next(
            (picked(rows, r) for r in rows.get_children() if r.get_child_visible()), None))
        box.add(search)
    box.add(scroller)
    box.show_all()
    rows.connect("row-activated", picked)
    popover.connect("show", lambda *_: GLib.idle_add(opened))
    return button


# --- banner and About ---

def system_info():
    os_name = platform.freedesktop_os_release().get("PRETTY_NAME", "Linux")
    with open("/proc/cpuinfo") as f:
        cpu = re.search(r"model name\s*: (.*)", f.read())
    cpu = re.sub(r"\((R|TM)\)|CPU ", "", cpu.group(1)) if cpu else platform.processor()
    with open("/proc/meminfo") as f:
        mem = int(re.search(r"MemTotal:\s*(\d+)", f.read()).group(1)) * 1024
    disk = shutil.disk_usage("/")
    with open("/proc/uptime") as f:
        up = int(float(f.read().split()[0]) / 60)
    days, hours, mins = up // 1440, up // 60 % 24, up % 60
    geo = Gdk.Display.get_default().get_monitor(0).get_geometry()
    return {
        "Computer name": socket.gethostname(),
        "Operating system": os_name,
        "Kernel": f"Linux {platform.release()}",
        "Processor": f"{' '.join(cpu.split())} · {os.cpu_count()} threads",
        "Memory": gb(mem),
        "Disk": f"{gb(disk.used)} used of {gb(disk.total)}",
        "Display": f"{geo.width} × {geo.height}",
        "Uptime": f"{days} d {hours} h" if days else f"{hours} h {mins} min",
    }


def gb(n):
    return f"{n / 1024 ** 3:.1f} GB"


def banner():
    info = system_info()
    box = css(Gtk.Box(spacing=20), "banner")
    box.add(image("start", 56))
    texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER)
    texts.add(label(info["Operating system"], "big"))
    texts.add(label(f"{info['Kernel']} · {os.cpu_count()}-thread {platform.machine()} · {info['Memory']}", "dim"))
    texts.add(label(f"{info['Computer name']} · {getpass.getuser()}", "chip", halign=Gtk.Align.START))
    box.add(texts)
    return box


def about_page():
    rows = [row(key, end=label(value, "value", xalign=1)) for key, value in system_info().items()]
    return page(heading("This computer"), card(rows))


# --- Appearance ---

PREVIEW = (480, 270)
THUMB = (160, 90)
THUMB_CACHE = os.path.join(GLib.get_user_cache_dir(), "shell", "thumbs")


def preview_pixbuf(path):
    """The image cropped to PREVIEW, cached: decoding a big photo takes a second."""
    key = hashlib.md5(f"{path}:{os.stat(path).st_mtime_ns}".encode()).hexdigest()
    cached = os.path.join(THUMB_CACHE, f"{key}.png")
    try:
        return GdkPixbuf.Pixbuf.new_from_file(cached)
    except GLib.Error:
        pixbuf = cover(path, *PREVIEW)
        os.makedirs(THUMB_CACHE, exist_ok=True)
        pixbuf.savev(cached, "png", [], [])
        return pixbuf


class AppearancePage(Gtk.ScrolledWindow):
    def __init__(self):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.preview = css(Gtk.Image(), "preview")
        self.preview.set_size_request(*PREVIEW)  # holds its place while loading
        self.grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4,
                                column_spacing=6, row_spacing=6, homogeneous=True)
        choose = Gtk.Button(label="Choose another picture…", halign=Gtk.Align.START)
        choose.connect("clicked", lambda *_: self._choose())
        box = css(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "page")
        for child in (heading("Wallpaper"), self.preview, heading("Pictures"), self.grid, choose):
            box.add(child)
        self.add(box)
        self.thumbs = {}
        try:
            with open(WALLPAPER_FILE) as f:
                self.current = f.read().strip()
        except OSError:
            self.current = None
        pictures = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or os.path.expanduser("~/Pictures")
        files = sorted(glob.glob(os.path.join(pictures, "*")), key=os.path.getmtime, reverse=True)
        # decoding happens off the main thread, so the page opens at once
        threading.Thread(target=self._load, args=(self.current, files), daemon=True).start()

    def _load(self, current, files):
        if current:
            self._load_one(current, self._show_preview)
        for path in files:
            self._load_one(path, self._add_thumb)

    def _load_one(self, path, done):
        # by name: reading the header of a big photo is slow
        if not Gio.content_type_guess(path, None)[0].startswith("image/"):
            return
        try:
            pixbuf = preview_pixbuf(path)
        except (OSError, GLib.Error):
            return
        GLib.idle_add(done, path, pixbuf)

    def _show_preview(self, path, pixbuf):
        if path == self.current:  # not if another one was picked meanwhile
            self.preview.set_from_pixbuf(pixbuf)
        return False

    def _add_thumb(self, path, pixbuf):
        button = css(Gtk.Button(tooltip_text=os.path.basename(path), halign=Gtk.Align.CENTER), "thumb")
        button.add(Gtk.Image.new_from_pixbuf(pixbuf.scale_simple(*THUMB, GdkPixbuf.InterpType.BILINEAR)))
        button.connect("clicked", lambda *_: self._set(path, pixbuf))
        self.thumbs[path] = button
        self.grid.add(button)
        button.show_all()
        self._mark_selected()
        return False

    def _mark_selected(self):
        for path, button in self.thumbs.items():
            ctx = button.get_style_context()
            (ctx.add_class if path == self.current else ctx.remove_class)("selected")

    def _set(self, path, pixbuf=None):
        save_wallpaper(path)  # the desktop watches the file
        self.current = path
        self._mark_selected()
        if pixbuf:
            self.preview.set_from_pixbuf(pixbuf)
        else:
            threading.Thread(target=self._load_one, args=(path, self._show_preview), daemon=True).start()

    def _choose(self):
        dialog = Gtk.FileChooserNative(title="Choose a wallpaper", action=Gtk.FileChooserAction.OPEN,
                                       transient_for=self.get_toplevel())
        images = Gtk.FileFilter()
        images.set_name("Images")
        images.add_pixbuf_formats()
        dialog.add_filter(images)
        dialog.set_current_folder(os.path.expanduser("~/Pictures"))
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            self._set(dialog.get_filename())
        dialog.destroy()


# --- Sound ---

class SoundPage(Gtk.ScrolledWindow):
    def __init__(self):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.outputs = Gtk.Box()
        self._shown = None
        self.vol = volume.Volume(self._changed)
        self.row = css(volume.VolumeRow(self.vol), "row")
        box = css(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "page")
        for child in (heading("Output"), self.outputs, heading("Volume"), card([self.row])):
            box.add(child)
        self.add(box)

    def _changed(self):
        self.row.refresh()
        volume.pactl("get-default-sink", done=lambda default: volume.pactl(
            "--format=json", "list", "sinks", done=lambda out: self._show_outputs(default.strip(), out)))

    def _show_outputs(self, default, out):
        try:
            sinks = [(s["name"], s["description"]) for s in json.loads(out)]
        except ValueError:
            return
        if (default, sinks) == self._shown:  # every volume step lands here too
            return
        self._shown = default, sinks
        rows = []
        for name, description in sinks:
            mark = image("check", 16) if name == default else None
            button = css(Gtk.Button(), "row")
            button.add(row(description, end=mark))
            button.connect("clicked", lambda *_, n=name: volume.pactl("set-default-sink", n))
            rows.append(button)
        self.outputs.foreach(lambda w: w.destroy())
        self.outputs.pack_start(card(rows or [row("No output devices")]), True, True, 0)
        self.outputs.show_all()


# --- Startup ---

def autostart_entries():
    """{file name: path}; a file in the user's folder overrides the system one."""
    entries = {}
    for d in AUTOSTART_DIRS:
        for path in glob.glob(os.path.join(d, "*.desktop")):
            entries[os.path.basename(path)] = path
    return entries


def key(kf, getter, name, default=None):
    try:
        return getter(DE, name)
    except GLib.Error:  # key not in the file
        return default


def shown_in_xfce(kf):
    only = key(kf, kf.get_string_list, "OnlyShowIn")
    return (only is None or "XFCE" in only) and "XFCE" not in key(kf, kf.get_string_list, "NotShowIn", [])


def enabled(kf):
    return not key(kf, kf.get_boolean, "Hidden", False) and key(kf, kf.get_boolean, "X-GNOME-Autostart-enabled", True)


def set_autostart(name, path, on):
    # a copy in the user's folder overrides the system entry, like Xfce's own settings do
    kf = GLib.KeyFile()
    kf.load_from_file(path, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
    kf.set_boolean(DE, "Hidden", not on)
    if key(kf, kf.get_boolean, "X-GNOME-Autostart-enabled") is not None:
        kf.set_boolean(DE, "X-GNOME-Autostart-enabled", on)
    os.makedirs(AUTOSTART_USER, exist_ok=True)
    kf.save_to_file(os.path.join(AUTOSTART_USER, name))


def startup_page():
    rows = []
    for name, path in autostart_entries().items():
        kf = GLib.KeyFile()
        try:
            kf.load_from_file(path, GLib.KeyFileFlags.NONE)
            title = kf.get_locale_string(DE, "Name", None)
        except GLib.Error:
            continue
        if not shown_in_xfce(kf):
            continue
        comment = key(kf, lambda g, k: kf.get_locale_string(g, k, None), "Comment")
        icon_name = key(kf, kf.get_string, "Icon", "application-x-executable")
        icon = Gtk.Image.new_from_gicon(Gio.Icon.new_for_string(icon_name), Gtk.IconSize.DND)
        icon.set_pixel_size(24)
        switch = Gtk.Switch(active=enabled(kf))
        switch.connect("state-set", lambda _s, on, n=name: set_autostart(n, autostart_entries()[n], on) or False)
        rows.append((title.lower(), row(title, comment, switch, icon)))
    return page(heading("Apps that start when you log in"), card([r for _, r in sorted(rows, key=lambda r: r[0])]))


# --- Keyboard ---
# xfsettingsd applies these the moment they change in xfconf

def xfconf_get(channel, prop, default):
    out = subprocess.run(["xfconf-query", "-c", channel, "-p", prop], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else default


def xfconf_set(channel, prop, kind, value):
    subprocess.run(["xfconf-query", "-c", channel, "-p", prop, "-n", "-t", kind, "-s", str(value)])


def layouts():
    """[(code, name)] from xkb's list, sorted by name."""
    found, section = [], None
    with open("/usr/share/X11/xkb/rules/evdev.lst") as f:
        for line in f:
            if line.startswith("!"):
                section = line.strip()
            elif section == "! layout" and line.strip():
                code, name = line.split(None, 1)
                found.append((code, name.strip()))
    return sorted(found, key=lambda layout: layout[1])


def current_layout():
    if xfconf_get("keyboard-layout", "/Default/XkbDisable", "true") == "false":
        return xfconf_get("keyboard-layout", "/Default/XkbLayout", "us").split(",")[0]
    # Xfce isn't managing it: whatever the system set
    out = subprocess.run(["setxkbmap", "-query"], capture_output=True, text=True).stdout
    m = re.search(r"layout:\s*([^,\s]+)", out)
    return m.group(1) if m else "us"


def set_layout(code):
    xfconf_set("keyboard-layout", "/Default/XkbLayout", "string", code)
    xfconf_set("keyboard-layout", "/Default/XkbVariant", "string", "")
    xfconf_set("keyboard-layout", "/Default/XkbDisable", "bool", "false")


def repeat_slider(prop, low, high, default, unit):
    """Slider for a key-repeat value, saved once it stops moving."""
    value = int(xfconf_get("keyboards", prop, default))
    scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, low, high, 1)
    scale.set_value(value)
    scale.set_draw_value(False)
    scale.set_size_request(260, -1)
    shown = label(f"{value} {unit}", "dim", width_chars=8, xalign=1)
    pending = []

    def save():
        pending.clear()
        xfconf_set("keyboards", prop, "int", int(scale.get_value()))
        return False

    def changed(s):
        shown.set_text(f"{int(s.get_value())} {unit}")
        if pending:  # dragging: one write at the end, not one per pixel
            GLib.source_remove(pending.pop())
        pending.append(GLib.timeout_add(300, save))
    scale.connect("value-changed", changed)
    box = css(Gtk.Box(spacing=10), "volume-row")  # same slider look as the volume
    box.add(scale)
    box.add(shown)
    return box


def shortcut_rows():
    out = subprocess.run(["xfconf-query", "-c", "xfce4-keyboard-shortcuts", "-l", "-v"],
                         capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        path, _, command = line.partition(" ")
        parts = path.split("/")  # ['', 'commands', 'custom', '<Super>space'], skipping sub-keys
        if len(parts) != 4 or parts[1:3] != ["commands", "custom"]:
            continue
        key, mods = Gtk.accelerator_parse(parts[3])
        if key:
            keys = css(Gtk.Label(label=Gtk.accelerator_get_label(key, mods)), "keys")
            program, _, args = command.strip().partition(" ")
            rows.append(row(f"{os.path.basename(program)} {args}".strip(), end=keys))
    return sorted(rows, key=lambda r: r.get_children()[-1].get_text().lower())


def keyboard_page():
    test = css(Gtk.Box(), "row")
    test.add(Gtk.Entry(placeholder_text="Type here to try the repeat settings", hexpand=True))
    return page(
        heading("Layout"),
        card([row("Keyboard layout", end=picker(layouts(), current_layout(), set_layout))]),
        heading("Typing"),
        card([row("Repeat delay", "How long to hold a key before it repeats",
                  repeat_slider("/Default/KeyRepeat/Delay", 100, 1000, 500, "ms")),
              row("Repeat speed", "Characters per second while held",
                  repeat_slider("/Default/KeyRepeat/Rate", 5, 80, 20, "/ s")),
              test]),
        heading("Shortcuts"),
        card(shortcut_rows()))


PAGES = {"appearance": AppearancePage, "sound": SoundPage, "startup": startup_page, "about": about_page,
         "keyboard": keyboard_page}


# --- window ---

class ControlPanel(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Control Panel", default_width=957, default_height=582)
        css(self, "settings")
        self.header = Gtk.HeaderBar(show_close_button=True, title="Control Panel",
                                    decoration_layout=":minimize,close")
        self.set_titlebar(self.header)
        self.back = Gtk.Button.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.BUTTON)
        self.back.connect("clicked", lambda *_: self.open(None))
        self.header.pack_start(self.back)
        self.search = Gtk.SearchEntry(placeholder_text="Search settings", width_chars=24)
        self.search.connect("search-changed", self._on_search)
        self.header.pack_end(self.search)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120)
        self.add(self.stack)
        home = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        home.add(banner())
        grid = css(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "home")
        self.sections = []  # (heading, flowbox, [(child, text)])
        for name, tiles in SECTIONS:
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=4,
                               max_children_per_line=4, column_spacing=10, row_spacing=10, homogeneous=True)
            items = []
            for tile_info in tiles:
                flow.add(self._tile(*tile_info))
                items.append((flow.get_children()[-1], " ".join(tile_info[1:3] + tile_info[5:]).lower()))
            head = heading(name)
            grid.add(head)
            grid.add(flow)
            self.sections.append((head, flow, items))
        home.add(grid)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.add(home)
        self.stack.add_named(scroller, "home")
        self.pages = {}
        self.show_all()
        self.back.hide()

    def _tile(self, name, title, subtitle, icon, colour, _words):
        button = css(Gtk.Button(sensitive=name in PAGES), "tile")
        box = Gtk.Box(spacing=12)
        badge = css(Gtk.Box(valign=Gtk.Align.CENTER), "badge", colour)
        badge.set_center_widget(image(icon, 18))
        box.add(badge)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
        texts.add(label(title, "title"))
        texts.add(label(subtitle, "dim", ellipsize=Pango.EllipsizeMode.END))
        box.add(texts)
        button.add(box)
        button.connect("clicked", lambda *_: self.open(name))
        return button

    def open(self, name):
        if name is None:
            self.stack.set_visible_child_name("home")
            self.header.set_title("Control Panel")
            self.back.hide()
            return
        if name not in self.pages:
            self.pages[name] = PAGES[name]()
            self.stack.add_named(self.pages[name], name)
            self.pages[name].show_all()
        self.stack.set_visible_child(self.pages[name])
        self.header.set_title(next(t[1] for _, tiles in SECTIONS for t in tiles if t[0] == name))
        self.back.show()

    def _on_search(self, entry):
        query = entry.get_text().strip().lower()
        if query:
            self.open(None)
        for head, flow, items in self.sections:
            for child, text in items:
                child.set_visible(query in text)
            visible = any(query in text for _, text in items)
            head.set_visible(visible)
            flow.set_visible(visible)


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="desktop.ControlPanel", flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)

    def do_startup(self):
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_path(CSS_FILE)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_command_line(self, cmd):
        # a second launch lands here in the running instance
        window = self.get_active_window() or ControlPanel(self)
        args = cmd.get_arguments()[1:]
        if args and args[0] in PAGES:
            window.open(args[0])
        window.present()
        return 0


if __name__ == "__main__":
    App().run(sys.argv)
