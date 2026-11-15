"""Taskbar: a bar docked to the bottom of the screen with a button per pinned or open app."""
import functools
import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GdkX11", "3.0")
gi.require_version("Wnck", "3.0")
from gi.repository import Gdk, GdkPixbuf, GdkX11, Gio, Gtk, Wnck  # noqa: E402

import x11  # noqa: E402
from launcher import StartButton, launch, menu_item, new_menu, own_icon  # noqa: E402
from tray import Tray  # noqa: E402

HEIGHT = 40
ICON = 24
DRAG_THRESHOLD = 8  # px before a press becomes a drag
CSS_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), "style.css")
ICONS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "icons")
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "shell")
PINNED_FILE = os.path.join(CONFIG_DIR, "pinned")

# window types that get a button (like Xfce's window list)
LISTED = (Wnck.WindowType.NORMAL, Wnck.WindowType.DIALOG)


@functools.cache
def wm_classes():
    """StartupWMClass (lowercase) -> app, for apps whose window class differs from their id."""
    return {a.get_startup_wm_class().lower(): a for a in Gio.AppInfo.get_all()
            if isinstance(a, Gio.DesktopAppInfo) and a.get_startup_wm_class()}


def desktop_app(app_id):
    try:
        return Gio.DesktopAppInfo.new(app_id)
    except TypeError:  # PyGObject raises instead of returning None for unknown ids
        return None


def app_for(window):
    """The installed app a window belongs to, or None."""
    for name in filter(None, (window.get_class_instance_name(), window.get_class_group_name())):
        app = (wm_classes().get(name.lower()) or desktop_app(f"{name}.desktop")
               or desktop_app(f"{name.lower()}.desktop"))
        if app:
            return app
    return None


def load_pinned():
    try:
        with open(PINNED_FILE) as f:
            return [line.strip() for line in f if line.strip()]
    except OSError:
        return []


class TaskButton(Gtk.Button):
    """A pinned app and/or all open windows of one app. Click to launch it or switch to it
    (minimize it if it's the only window and active), click again to cycle its windows,
    right-click for a window list."""

    def __init__(self, bar, key, app, group):
        super().__init__(relief=Gtk.ReliefStyle.NONE, has_tooltip=True)
        self.bar = bar
        self.key = key      # app id, or the class group for windows of no known app
        self.app = app
        self.group = group
        self.windows = []   # in opening order
        self.menu = None
        self._press_x = None
        self.dragging = False
        self.get_style_context().add_class("task")
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK)

        self.image = Gtk.Image()
        # badge on the icon's bottom-right corner when the app has several windows
        self.plus = Gtk.Image.new_from_file(os.path.join(ICONS, "plus.svg"))
        self.plus.set_halign(Gtk.Align.END)
        self.plus.set_valign(Gtk.Align.END)
        self.plus.set_margin_end(8)
        self.plus.set_margin_bottom(5)
        self.plus.set_no_show_all(True)
        overlay = Gtk.Overlay()
        overlay.add(self.image)
        overlay.add_overlay(self.plus)
        self.add(overlay)

        self._icon_handler = None
        if app and app.get_icon():
            self.image.set_from_gicon(app.get_icon(), Gtk.IconSize.BUTTON)
            self.image.set_pixel_size(ICON)
        else:
            self._update_icon()
            self._icon_handler = group.connect("icon-changed", lambda *_: self._update_icon())

        self.connect("query-tooltip", self._on_tooltip)
        self.connect("button-press-event", self._on_press)
        self.connect("motion-notify-event", self._on_motion)
        self.connect("button-release-event", self._on_release)

    def update_state(self):
        self.plus.set_visible(len(self.windows) > 1)
        ctx = self.get_style_context()
        (ctx.remove_class if self.windows else ctx.add_class)("idle")

    def disconnect_group(self):
        if self._icon_handler:
            self.group.disconnect(self._icon_handler)

    def _update_icon(self):
        pix = self.group.get_icon()
        if pix.get_width() != ICON:
            pix = pix.scale_simple(ICON, ICON, GdkPixbuf.InterpType.BILINEAR)
        self.image.set_from_pixbuf(pix)

    def _name(self):
        return self.app.get_display_name() if self.app else self.group.get_name()

    def _on_tooltip(self, _w, _x, _y, _kb, tooltip):
        if len(self.windows) == 1:
            tooltip.set_text(self.windows[0].get_name())
        elif self.windows:
            tooltip.set_text(f"{self._name()} ({len(self.windows)})")
        else:
            tooltip.set_text(self._name())
        return True

    def _show_menu(self, ev):
        self.menu = new_menu()
        for window in self.windows:
            item = menu_item(window.get_name(), window.get_mini_icon())
            item.connect("activate", lambda _i, w=window: w.activate(Gtk.get_current_event_time()))
            self.menu.append(item)
        if self.windows:
            self.menu.append(Gtk.SeparatorMenuItem())
        if self.app:
            pinned = self.key in self.bar.pinned
            pin = menu_item("Unpin from taskbar" if pinned else "Pin to taskbar",
                            own_icon("check" if pinned else "blank"))  # blank keeps text aligned
            pin.connect("activate", lambda *_: (self.bar.unpin if pinned else self.bar.pin)(self))
            self.menu.append(pin)
        if self.windows:
            close = menu_item("Close all windows" if len(self.windows) > 1 else "Close window",
                              own_icon("close"))
            close.connect("activate", lambda *_: self._close_all())
            self.menu.append(close)
        self.menu.attach_to_widget(self, None)
        self.menu.show_all()
        self.menu.popup_at_widget(self, Gdk.Gravity.NORTH_WEST, Gdk.Gravity.SOUTH_WEST, ev)

    def _close_all(self):
        for window in list(self.windows):
            window.close(Gtk.get_current_event_time())

    # click / drag

    def _on_press(self, _w, ev):
        if ev.button == 1:
            self._press_x = ev.x_root
            self.dragging = False
        elif ev.button == 3:
            self._show_menu(ev)
        return True  # we handle clicks ourselves

    def _on_motion(self, _w, ev):
        if self._press_x is None:
            return False
        if not self.dragging and abs(ev.x_root - self._press_x) > DRAG_THRESHOLD:
            self.dragging = True
            self.get_style_context().add_class("dragging")
        if self.dragging:
            self.bar.drag_to(self, ev.x_root)
        return True

    def _on_release(self, _w, ev):
        if ev.button != 1 or self._press_x is None:
            return True
        self._press_x = None
        if self.dragging:
            self.dragging = False
            self.get_style_context().remove_class("dragging")
            self.bar.save_pinned()
            return True
        active = self.bar.wnck.get_active_window()
        if not self.windows:
            launch(self.app)
        elif active not in self.windows:
            self.windows[0].activate(ev.time)
        elif len(self.windows) == 1:
            active.minimize()
        else:
            nxt = self.windows[(self.windows.index(active) + 1) % len(self.windows)]
            nxt.activate(ev.time)
        return True


class Taskbar(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.set_title("taskbar")
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)   # clicking the bar must not take focus from apps
        self.set_focus_on_map(False)
        self.stick()
        self.get_style_context().add_class("taskbar")

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.set_visual(visual)  # lets the CSS background be translucent

        provider = Gtk.CssProvider()
        provider.load_from_path(CSS_FILE)
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        bar = Gtk.Box()
        self.tasks = Gtk.Box()
        self.start = StartButton()
        bar.pack_start(self.start, False, False, 0)
        bar.pack_start(self.tasks, True, True, 0)
        bar.pack_end(Tray(), False, False, 0)
        self.add(bar)
        self.groups = {}   # TaskButton.key -> TaskButton
        self.buttons = {}  # Wnck.Window -> TaskButton

        self.pinned = []
        for app_id in load_pinned():
            app = desktop_app(app_id)
            if app:  # skip apps that were uninstalled
                self.pinned.append(app_id)
                self._new_button(app_id, app, None)

        Wnck.set_default_icon_size(32)
        self.wnck = Wnck.Screen.get_default()
        self.wnck.force_update()
        for w in self.wnck.get_windows():
            self._track(w)
        self.wnck.connect("window-opened", lambda _s, w: self._track(w))
        self.wnck.connect("window-closed", lambda _s, w: self._remove(w))
        self.wnck.connect("active-window-changed", lambda *_: self._mark_active())
        self._mark_active()

        self.connect("realize", lambda *_: self._place())

    # windows

    def _new_button(self, key, app, group):
        button = self.groups[key] = TaskButton(self, key, app, group)
        self.tasks.pack_start(button, False, False, 0)
        button.show_all()
        button.update_state()
        return button

    def _drop(self, button):
        del self.groups[button.key]
        button.disconnect_group()
        button.destroy()

    def _track(self, window):
        # every window, listed or not: a skipped one may ask to be listed later
        window.connect("state-changed", lambda w, *_: self._on_state(w))
        self._add(window)

    def _add(self, window):
        if window in self.buttons or window.is_skip_tasklist() or window.get_window_type() not in LISTED:
            return
        app = app_for(window)
        key = app.get_id() if app else window.get_class_group()
        button = self.groups.get(key) or self._new_button(key, app, window.get_class_group())
        button.windows.append(window)
        button.update_state()
        self.buttons[window] = button

    def _remove(self, window):
        button = self.buttons.pop(window, None)
        if not button:
            return
        button.windows.remove(window)
        button.update_state()
        if not button.windows and button.key not in self.pinned:
            self._drop(button)

    def _on_state(self, window):
        # a window can start or stop asking to be left out of taskbars
        if window.is_skip_tasklist():
            self._remove(window)
        else:
            self._add(window)
            self._mark_active()

    def _mark_active(self):
        active = self.wnck.get_active_window()
        for button in self.groups.values():
            ctx = button.get_style_context()
            (ctx.add_class if active in button.windows else ctx.remove_class)("active")

    # pinning

    def pin(self, button):
        self.pinned.append(button.key)
        self.save_pinned()

    def unpin(self, button):
        self.pinned.remove(button.key)
        self.save_pinned()
        if not button.windows:
            self._drop(button)

    def save_pinned(self):
        # pinned order is their order on the bar
        self.pinned = [b.key for b in self.tasks.get_children() if b.key in self.pinned]
        os.makedirs(os.path.dirname(PINNED_FILE), exist_ok=True)
        with open(PINNED_FILE, "w") as f:
            f.writelines(f"{app_id}\n" for app_id in self.pinned)

    # reordering

    def drag_to(self, button, x_root):
        """Move `button` to the slot under the pointer (works in both directions)."""
        origin_x = self.get_window().get_origin()[1]
        x = x_root - origin_x
        others = [b for b in self.tasks.get_children() if b is not button]
        index = sum(1 for b in others
                    if b.get_allocation().x + b.get_allocation().width / 2 < x)
        if self.tasks.get_children().index(button) != index:
            self.tasks.reorder_child(button, index)

    # placement

    def _place(self):
        display = self.get_display()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        geo = monitor.get_geometry()
        self.set_size_request(geo.width, HEIGHT)
        self.move(geo.x, geo.y + geo.height - HEIGHT)
        root_height = self.get_screen().get_root_window().get_height()
        bottom = root_height - (geo.y + geo.height) + HEIGHT
        xid = GdkX11.X11Window.get_xid(self.get_window())
        x11.reserve_bottom(xid, bottom, geo.x, geo.x + geo.width - 1)
