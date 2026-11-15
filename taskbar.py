"""Taskbar: a bar docked to the bottom of the screen with a button per open window."""
import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GdkX11", "3.0")
gi.require_version("Wnck", "3.0")
from gi.repository import Gdk, GdkPixbuf, GdkX11, Gtk, Wnck  # noqa: E402

import x11  # noqa: E402
from launcher import StartButton  # noqa: E402
from tray import Tray  # noqa: E402

HEIGHT = 40
ICON = 24
DRAG_THRESHOLD = 8  # px before a press becomes a drag
CSS_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), "style.css")

# window types that get a button (like Xfce's window list)
LISTED = (Wnck.WindowType.NORMAL, Wnck.WindowType.DIALOG)


class WindowButton(Gtk.Button):
    """One open window: click to switch to it (or minimize it if active), drag to reorder."""

    def __init__(self, bar, window):
        super().__init__(relief=Gtk.ReliefStyle.NONE)
        self.bar = bar
        self.window = window
        self._press_x = None
        self.dragging = False
        self.get_style_context().add_class("task")
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK)

        self.image = Gtk.Image()
        self.add(self.image)
        self._update_icon()
        self._update_title()

        self._handlers = [
            window.connect("icon-changed", lambda *_: self._update_icon()),
            window.connect("name-changed", lambda *_: self._update_title()),
        ]
        self.connect("button-press-event", self._on_press)
        self.connect("motion-notify-event", self._on_motion)
        self.connect("button-release-event", self._on_release)

    def disconnect_window(self):
        for h in self._handlers:
            self.window.disconnect(h)

    def _update_icon(self):
        pix = self.window.get_icon()
        if pix.get_width() != ICON:
            pix = pix.scale_simple(ICON, ICON, GdkPixbuf.InterpType.BILINEAR)
        self.image.set_from_pixbuf(pix)

    def _update_title(self):
        self.set_tooltip_text(self.window.get_name())

    # click / drag

    def _on_press(self, _w, ev):
        if ev.button == 1:
            self._press_x = ev.x_root
            self.dragging = False
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
        elif self.window.is_active():
            self.window.minimize()
        else:
            self.window.activate(ev.time)
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
        self.buttons = {}  # Wnck.Window -> WindowButton

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

    def _track(self, window):
        # every window, listed or not: a skipped one may ask to be listed later
        window.connect("state-changed", lambda w, *_: self._on_state(w))
        self._add(window)

    def _add(self, window):
        if window in self.buttons or window.is_skip_tasklist() or window.get_window_type() not in LISTED:
            return
        button = WindowButton(self, window)
        self.buttons[window] = button
        self.tasks.pack_start(button, False, False, 0)
        button.show_all()

    def _remove(self, window):
        button = self.buttons.pop(window, None)
        if button:
            button.disconnect_window()
            button.destroy()

    def _on_state(self, window):
        # a window can start or stop asking to be left out of taskbars
        if window.is_skip_tasklist():
            self._remove(window)
        else:
            self._add(window)
            self._mark_active()

    def _mark_active(self):
        active = self.wnck.get_active_window()
        for window, button in self.buttons.items():
            ctx = button.get_style_context()
            (ctx.add_class if window == active else ctx.remove_class)("active")

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
