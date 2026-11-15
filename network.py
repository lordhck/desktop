"""Network icon in the tray, with a popup to manage Wi-Fi (through nmcli)."""
import fcntl
import os
import re
import socket
import struct
from html import escape

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango  # noqa: E402

from launcher import ICONS, run  # noqa: E402

ICON = 20
PERIOD = 3        # seconds between status checks
LIST_HEIGHT = 340
DNS = {"Auto": [], "Cloudflare": ["1.1.1.1", "1.0.0.1"], "Google": ["8.8.8.8", "8.8.4.4"],
       "Quad9": ["9.9.9.9", "149.112.112.112"]}


def default_route():
    """(interface, gateway) of the default route with the lowest metric, or (None, None)."""
    best = None
    try:
        with open("/proc/net/route") as f:
            next(f)
            for p in map(str.split, f):
                if p[1] == "00000000" and int(p[3], 16) & 1 and (not best or int(p[6]) < best[2]):
                    best = (p[0], socket.inet_ntoa(struct.pack("<I", int(p[2], 16))), int(p[6]))
    except OSError:
        pass
    return best[:2] if best else (None, None)


def traffic(iface):
    """(received, sent) bytes since the interface came up."""
    stats = f"/sys/class/net/{iface}/statistics"
    try:
        return tuple(int(open(f"{stats}/{k}_bytes").read()) for k in ("rx", "tx"))
    except OSError:
        return 0, 0


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def ipv4(iface):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:  # SIOCGIFADDR
            return socket.inet_ntoa(fcntl.ioctl(s.fileno(), 0x8915, struct.pack("256s", iface.encode()[:15]))[20:24])
        except OSError:
            return "—"


def wifi_blocked():
    rfkill = "/sys/class/rfkill"
    try:
        return any(open(f"{rfkill}/{r}/type").read().strip() == "wlan"
                   and open(f"{rfkill}/{r}/soft").read().strip() == "1" for r in os.listdir(rfkill))
    except OSError:
        return False


def set_wifi(on):
    """Turn Wi-Fi on/off through /dev/rfkill (no root needed)."""
    # struct rfkill_event { u32 idx; u8 type; u8 op; u8 soft; u8 hard; }: type 1 = WLAN, op 3 = CHANGE_ALL
    with open("/dev/rfkill", "wb", buffering=0) as f:
        f.write(struct.pack("IBBBB", 0, 1, 3, 0 if on else 1, 0))


def level(signal):
    return 0 if signal is None else 3 if signal >= 70 else 2 if signal >= 45 else 1 if signal >= 20 else 0


def pix(name, size):
    return GdkPixbuf.Pixbuf.new_from_file_at_size(os.path.join(ICONS, f"{name}.svg"), size, size)


def image(name, size):
    return Gtk.Image.new_from_pixbuf(pix(name, size))


def css(widget, *classes):
    for c in classes:
        widget.get_style_context().add_class(c)
    return widget


def label(text="", *classes, **kw):
    return css(Gtk.Label(label=text, **{"xalign": 0, **kw}), *classes)


def notify(title, body="", icon="wifi-3"):
    run("notify-send", "-a", "Network", "-i", os.path.join(ICONS, f"{icon}.svg"), title, body)


def nmcli(args, done=None):
    """Run nmcli without blocking; done(ok, text) gets stdout, or the error on failure."""
    proc = Gio.Subprocess.new(["nmcli", *args], Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)

    def finished(p, result):
        _, out, err = p.communicate_utf8_finish(result)
        if done:
            done(p.get_successful(), out if p.get_successful() else err.strip().removeprefix("Error: "))
    proc.communicate_utf8_async(None, None, finished)


def fields(line):
    """Split an `nmcli -t` line (':' separated, '\\:' escaped)."""
    return [f.replace("\\:", ":").replace("\\\\", "\\") for f in re.split(r"(?<!\\):", line)]


def qr_pixbuf(text):
    # text on stdin: keeps a password out of the process list
    proc = Gio.Subprocess.new(["qrencode", "-t", "PNG", "-s", "4", "-m", "2", "-o", "-"],
                              Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE)
    _, png, _ = proc.communicate(GLib.Bytes.new(text.encode()), None)
    loader = GdkPixbuf.PixbufLoader.new_with_type("png")
    loader.write_bytes(png)
    loader.close()
    return loader.get_pixbuf()


class NetItem(Gtk.Button):
    """Tray icon: signal bars, wired or offline; click opens the popup."""

    def __init__(self):
        super().__init__(relief=Gtk.ReliefStyle.NONE)
        self.get_style_context().add_class("tray-item")
        self.image = Gtk.Image()
        self.add(self.image)
        self.nets, self.iface, self.status, self.popup = [], None, None, None
        self._conn = None  # last connection key; None until the first check
        self.connect("clicked", lambda *_: self.popup or Popup(self))
        self.poll()
        GLib.timeout_add_seconds(PERIOD, self.poll)

    def poll(self):
        nmcli(["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "no"], self._update)
        return True

    def _update(self, ok, out):
        nets = {}
        for line in out.splitlines() if ok else []:
            inuse, ssid, signal, security = fields(line)
            if ssid and (ssid not in nets or inuse == "*"):  # one row per SSID, strongest first
                nets[ssid] = {"ssid": ssid, "active": inuse == "*", "signal": int(signal or 0),
                              "security": security}
        self.nets = sorted(nets.values(), key=lambda n: (not n["active"], -n["signal"]))
        active = next((n for n in self.nets if n["active"]), None)

        iface, self.gateway = default_route()
        self.iface = iface
        ip = ipv4(iface) if iface else "—"
        if not iface:
            off = wifi_blocked()
            self.status = ("offline", "Wi-Fi off" if off else "Offline",
                           "Wi-Fi is turned off" if off else "Not connected")
            tip, conn = "No active network connection", ("", "", "")
        elif os.path.isdir(f"/sys/class/net/{iface}/wireless"):
            ssid, signal = (active["ssid"], active["signal"]) if active else ("Wi-Fi", None)
            self.status = (f"wifi-{level(signal)}", ssid, f"Connected · Signal {signal}%" if active else "Connected")
            tip = f"WiFi: {escape(ssid)}\nSignal: {f'{signal}%' if active else '—'}\nIPv4: {ip}"
            conn = (f"{iface}|{ssid}", f"Connected to {ssid}", f"Signal {signal}% · {ip}" if active else ip)
        else:
            self.status = ("wired", "Wired", f"Connected · {iface}")
            tip, conn = f"Wired: {iface}\nIPv4: {ip}", (iface, "Wired connection", f"{iface} · {ip}")
        self.image.set_from_pixbuf(pix(self.status[0], ICON))
        self.set_tooltip_markup(tip)
        if ip != "—" or not iface:  # wait for an IP before announcing a connection
            if conn[0] and self._conn not in (None, conn[0]):
                notify(conn[1], conn[2], self.status[0])
            self._conn = conn[0]
        if self.popup:
            self.popup.refresh()


class Popup(Gtk.Window):
    """Start-menu-style box above the tray icon: status, networks, and a footer strip."""

    def __init__(self, item):
        # override-redirect (like GtkMenu): the WM won't move or constrain it
        super().__init__(type=Gtk.WindowType.POPUP)
        self.item, self.saved, self.busy, self._shown = item, set(), False, None
        item.popup = self
        css(self, "network")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(box)

        head = css(Gtk.Box(spacing=12), "head")
        self.head_img = Gtk.Image()
        head.add(self.head_img)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
        self.title = label("", "title", ellipsize=Pango.EllipsizeMode.END, max_width_chars=28)
        self.subtitle = label("", "dim")
        texts.add(self.title)
        texts.add(self.subtitle)
        head.pack_start(texts, True, True, 0)
        self.switch = Gtk.Switch(active=not wifi_blocked(), valign=Gtk.Align.CENTER, tooltip_text="Wi-Fi on/off")
        self.switch_handler = self.switch.connect(
            "state-set", lambda _s, on: set_wifi(on))
        head.add(self.switch)
        box.add(head)
        box.add(Gtk.Separator())

        # the list and the sheets swap in place, so the box never resizes
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        # EXTERNAL: scrollable without a scrollbar
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                      vscrollbar_policy=Gtk.PolicyType.EXTERNAL, min_content_height=LIST_HEIGHT)
        scroller.add(self.list)
        self.stack.add_named(scroller, "list")
        self.sheet = css(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "sheet")
        self.stack.add_named(self.sheet, "sheet")
        box.add(self.stack)

        # like Power / Lock at the bottom of the Start menu
        foot = css(Gtk.Box(homogeneous=True), "footer")
        self.share = Gtk.Button()
        self.share.connect("clicked", lambda *_: self._share())
        scan = Gtk.Button()
        scan.connect("clicked", lambda *_: nmcli(["dev", "wifi", "rescan"], lambda *_: item.poll()))
        for button, icon, text in ((self.share, "qr", "Share"), (scan, "refresh", "Scan")):
            content = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
            content.add(image(icon, 14))
            content.add(Gtk.Label(label=text))
            button.add(content)
            foot.add(button)
        box.add(foot)

        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("key-press-event", self._on_key)
        self.connect("button-press-event", self._on_button)
        self.connect("map-event", lambda *_: GLib.timeout_add(30, self._grab, 20))
        self.connect("destroy", self._on_destroy)

        self.refresh()
        self._load_saved()
        nmcli(["dev", "wifi", "rescan"], lambda *_: item.poll())
        box.show_all()
        self.realize()
        self._place()  # before mapping, so it doesn't jump
        self.show()

    def _load_saved(self):
        def done(ok, out):
            self.saved = {f[0] for f in map(fields, out.splitlines()) if f[-1] == "802-11-wireless"} if ok else set()
            self._shown = None
            self.refresh()
        nmcli(["-t", "-f", "NAME,TYPE", "con", "show"], done)

    def _header(self, icon, title, sub, kind=None):
        self.head_img.set_from_pixbuf(pix(icon, 32))
        self.title.set_text(title)
        self.subtitle.set_text(sub)
        ctx = self.subtitle.get_style_context()
        for k in ("good", "bad"):
            (ctx.add_class if k == kind else ctx.remove_class)(k)

    def refresh(self):
        if not self.busy:
            self._header(*self.item.status)
        blocked = wifi_blocked()
        self.share.set_sensitive(any(n["active"] for n in self.item.nets) and not self.busy)
        if self.switch.get_active() == blocked:  # changed elsewhere, e.g. a hotkey
            self.switch.handler_block(self.switch_handler)
            self.switch.set_active(not blocked)
            self.switch.handler_unblock(self.switch_handler)
        nets = [] if blocked else self.item.nets
        shown = (blocked, tuple((n["ssid"], n["active"], level(n["signal"]), n["ssid"] in self.saved) for n in nets))
        if shown == self._shown:  # rebuild only on change: keeps hover and scroll position
            return
        self._shown = shown
        for c in self.list.get_children():
            c.destroy()
        if not nets:
            self.list.add(label("Wi-Fi is turned off" if blocked else "Looking for networks…", "dim",
                                xalign=0.5, height_request=LIST_HEIGHT))
        for n in nets:
            self.list.add(self._row(n))
        self.list.show_all()

    def _row(self, n):
        saved = n["ssid"] in self.saved
        b = css(Gtk.Button(relief=Gtk.ReliefStyle.NONE), "net")
        b.set_tooltip_text(f"{n['security'] or 'Open'} · Signal {n['signal']}%"
                           + ("\nRight-click for options" if saved and not n["active"] else ""))
        row = Gtk.Box(spacing=10)
        row.add(image(f"wifi-{level(n['signal'])}", 16))
        row.pack_start(label(n["ssid"], *(["title"] if n["active"] else []), ellipsize=Pango.EllipsizeMode.END),
                       True, True, 0)
        if n["active"]:
            row.add(image("check", 14))
        elif saved:
            row.add(label("Saved", "dim"))
        if n["security"]:
            row.add(css(image("lock", 12), "lock"))
        b.add(row)
        b.connect("clicked", lambda *_: self._connect(n) if (saved or not n["security"]) and not n["active"]
                  else self._network(n))
        b.connect("button-press-event", lambda _b, ev: ev.button == 3 and self._network(n))
        return b

    # sheets

    def _open_sheet(self, title, sub=None, icon=None):
        self._stop_rates()
        for c in self.sheet.get_children():
            c.destroy()
        top = Gtk.Box(spacing=10)
        if icon:
            top.add(image(icon, 24))
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, valign=Gtk.Align.CENTER)
        texts.add(label(title, "title", ellipsize=Pango.EllipsizeMode.END))
        if sub:
            texts.add(label(sub, "dim", ellipsize=Pango.EllipsizeMode.END))
        top.pack_start(texts, True, True, 0)
        close = css(Gtk.Button(valign=Gtk.Align.CENTER, tooltip_text="Back"), "icon")
        close.add(image("close", 14))
        close.connect("clicked", lambda *_: self._close_sheet())
        top.add(close)
        self.sheet.add(top)
        return self.sheet

    def _buttons(self, actions):
        """Show the sheet with (text, style, action) buttons at the bottom: "danger" ones
        on the left, the rest on the right. Returns the last button."""
        row = Gtk.Box(valign=Gtk.Align.END, vexpand=True)
        right = Gtk.Box(spacing=8)
        row.pack_end(right, False, False, 0)
        btn = None
        for text, style, action in actions:
            btn = css(Gtk.Button(label=text), *([style] if style else []))
            btn.connect("clicked", lambda _b, a=action: a())
            (row.pack_start(btn, False, False, 0) if style == "danger" else right.add(btn))
        self.sheet.add(row)
        self._show_sheet()
        return btn

    def _show_sheet(self):
        self.sheet.show_all()
        self.stack.set_visible_child(self.sheet)

    def _close_sheet(self):
        self._stop_rates()
        self.stack.set_visible_child_name("list")

    def _stop_rates(self):
        if getattr(self, "_rates", None):
            GLib.source_remove(self._rates)
        self._rates = None

    def _details(self, n):
        """Security, IP, gateway, live traffic and DNS of the current connection."""
        panel = css(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14), "details")
        grid = Gtk.Grid(column_spacing=16, row_spacing=8)
        panel.add(grid)
        iface = self.item.iface
        values = {"Security": label(n["security"] or "Open", "value", hexpand=True, xalign=1)}
        for key, value in (("IP address", ipv4(iface)), ("Gateway", self.item.gateway or "—")):
            values[key] = css(Gtk.Button(label=value, hexpand=True, halign=Gtk.Align.END,
                                         tooltip_text="Click to copy"), "copy")
            values[key].connect("clicked", self._copy, value)
        for key in ("Download", "Upload"):
            values[key] = label("—", "value", hexpand=True, xalign=1)
        for row, (key, widget) in enumerate(values.items()):
            grid.attach(label(key, "dim"), 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
        last = [traffic(iface)]

        def tick():
            now = traffic(iface)
            for key, before, total in zip(("Download", "Upload"), last[0], now):
                values[key].set_markup(f"{human(max(total - before, 0))}/s  "
                                       f"<span alpha='55%'>· {human(total)}</span>")
            last[0] = now
            return True
        tick()
        self._rates = GLib.timeout_add_seconds(1, tick)
        panel.add(self._dns(iface))
        return panel

    def _dns(self, iface):
        """Segmented DNS provider picker for the active connection."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.add(label("DNS", "dim"))
        strip = css(Gtk.Box(homogeneous=True), "segments")
        box.add(strip)
        buttons, con = {}, [None]

        def select(name):
            for key, b in buttons.items():
                (b.get_style_context().add_class if key == name else b.get_style_context().remove_class)("selected")

        def loaded(ok, out):
            rows = [fields(line) for line in out.splitlines()] if ok else []
            con[0] = next((r[-1] for r in rows if r[0] == "GENERAL.CONNECTION"), None)
            dns = [r[-1] for r in rows if r[0].startswith("IP4.DNS")]
            select(next((k for k, servers in DNS.items() if dns and dns[0] in servers), "Auto"))

        def load():
            nmcli(["-t", "-f", "GENERAL.CONNECTION,IP4.DNS", "dev", "show", iface], loaded)

        def applied(ok, err):
            if not ok:
                self.status.set_text(f"Couldn't change DNS: {err}")
                css(self.status, "bad")
                load()

        def choose(name):
            if not con[0]:
                return
            select(name)
            custom = "yes" if DNS[name] else "no"
            # IPv6 too: otherwise the router's IPv6 DNS would still be used
            nmcli(["con", "mod", con[0], "ipv4.dns", " ".join(DNS[name]),
                   "ipv4.ignore-auto-dns", custom, "ipv6.ignore-auto-dns", custom],
                  lambda ok, err: nmcli(["dev", "reapply", iface], applied) if ok else applied(ok, err))

        for name, servers in DNS.items():
            buttons[name] = Gtk.Button(label=name, tooltip_text=" · ".join(servers) or "From the router")
            buttons[name].connect("clicked", lambda _b, n=name: choose(n))
            strip.add(buttons[name])
        load()
        return box

    def _copy(self, button, value):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(value, -1)
        button.set_label("Copied")
        GLib.timeout_add(1000, lambda: button.set_label(value) and False)

    def _network(self, n, error=None):
        """Sheet for one network: password, or forget/disconnect."""
        # the header already shows the current network
        p = (self._open_sheet("Connection details") if n["active"] else
             self._open_sheet(n["ssid"], f"{n['security'] or 'Open'} · Signal {n['signal']}%",
                              f"wifi-{level(n['signal'])}"))
        entry = None
        if not n["active"] and n["security"]:
            entry = Gtk.Entry(visibility=False, placeholder_text="Password")
            entry.set_icon_from_pixbuf(Gtk.EntryIconPosition.SECONDARY, pix("eye", 16))
            entry.connect("icon-press", lambda e, *_: (e.set_visibility(not e.get_visibility()), e.set_icon_from_pixbuf(
                Gtk.EntryIconPosition.SECONDARY, pix("eye-off" if e.get_visibility() else "eye", 16))))
            p.add(entry)
        if n["active"]:
            p.add(self._details(n))
        self.status = label(error or "", "dim", *(["bad"] if error else []), wrap=True, max_width_chars=40)
        p.add(self.status)
        actions = []
        if n["ssid"] in self.saved:
            actions.append(("Forget", "danger", lambda: nmcli(["con", "delete", "id", n["ssid"]], self._done)))
        if n["active"]:
            actions.append(("Disconnect", None, lambda: nmcli(["dev", "disconnect", self.item.iface], self._done)))
        else:
            actions += [("Cancel", None, self._close_sheet),
                        ("Connect", "primary", lambda: self._connect(n, entry and entry.get_text()))]
        last = self._buttons(actions)
        if entry:
            entry.connect("activate", lambda e: self._connect(n, e.get_text()))
            entry.connect("changed", lambda e: last.set_sensitive(len(e.get_text()) >= 5))  # WEP: 5, WPA: 8
            last.set_sensitive(False)
            entry.grab_focus()

    def _share(self):
        def done(ok, out):
            info = dict(line.split(": ", 1) for line in out.splitlines() if ": " in line) if ok else {}
            p = self._open_sheet("Share Wi-Fi", "Scan with a phone to join")
            esc = lambda s: re.sub(r'([\\;,:"])', r"\\\1", s)  # noqa: E731
            kind = info.get("Security") if info.get("Security") in ("WPA", "WEP") else "nopass"
            try:
                qr = qr_pixbuf(f"WIFI:T:{kind};S:{esc(info['SSID'])};P:{esc(info.get('Password', ''))};;")
                p.add(Gtk.Image(pixbuf=qr, vexpand=True, valign=Gtk.Align.CENTER))
            except (GLib.Error, KeyError):
                p.add(label(out if not ok else "Install qrencode to share: sudo apt install qrencode",
                            "dim", wrap=True, max_width_chars=40))
            self._show_sheet()
        nmcli(["dev", "wifi", "show-password"], done)

    # actions

    def _connect(self, n, password=None):
        if self.busy:
            return
        self.busy = True
        self._close_sheet()
        self.share.set_sensitive(False)
        self._header(f"wifi-{level(n['signal'])}", n["ssid"], "Connecting…")

        def done(ok, err):
            self.busy = False
            if ok:
                self._header(f"wifi-{level(n['signal'])}", n["ssid"], "Connected", "good")
                self._load_saved()
            elif "Secrets were required" in err:  # no saved password, or a wrong one
                self.refresh()
                self._network(n, "Wrong password. Try again." if password else None)
            else:
                self._header("offline", n["ssid"], f"Couldn't connect: {err}", "bad")
            self.item.poll()
        nmcli(["dev", "wifi", "connect", n["ssid"]] + (["password", password] if password else []), done)

    def _done(self, ok, err):
        if not ok:
            self.status.set_text(err)
            css(self.status, "bad")
            return
        self._close_sheet()
        self._load_saved()
        self.item.poll()

    # placement and input

    def _place(self):
        """On top of the taskbar like the Start menu, right edge at the icon, kept on screen."""
        size = self.get_preferred_size()[1]
        gw = self.item.get_window()
        _, ox, oy = gw.get_origin()
        a = self.item.get_allocation()
        geo = Gdk.Display.get_default().get_monitor_at_window(gw).get_geometry()
        x = min(ox + a.x + a.width, geo.x + geo.width) - size.width
        self.move(max(x, geo.x), oy + a.y - size.height)

    def _grab(self, tries):
        """Grab input so outside clicks close the popup."""
        self.grab_add()  # clicks on the taskbar (same process) reach us too
        status = Gdk.Display.get_default().get_default_seat().grab(
            self.get_window(), Gdk.SeatCapabilities.ALL, True, None, None, None)
        if status == Gdk.GrabStatus.SUCCESS:
            return False
        return tries > 0 and GLib.timeout_add(50, self._grab, tries - 1) and False

    def _on_key(self, _w, ev):
        if ev.keyval != Gdk.KEY_Escape:
            return False
        if self.stack.get_visible_child() is self.sheet:
            self._close_sheet()
        else:
            self.destroy()
        return True

    def _on_button(self, _w, ev):
        _, ox, oy = self.get_window().get_origin()
        w, h = self.get_size()
        if not (0 <= ev.x_root - ox < w and 0 <= ev.y_root - oy < h):
            self.destroy()
            return True
        return False

    def _on_destroy(self, *_):
        self._stop_rates()
        self.grab_remove()
        Gdk.Display.get_default().get_default_seat().ungrab()
        self.item.popup = None
