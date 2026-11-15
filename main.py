#!/usr/bin/env python3
"""Desktop shell for Xfce (runs on xfwm4).

    main.py           start the shell
    main.py --menu    open/close the Start menu of the running shell (bind to Super)
    main.py --reload  restart the running shell to pick up code changes
    main.py --volume up|down|mute   for the media keys, same rules as the tray
"""
import locale
import os
import re
import signal
import subprocess
import sys

PIDFILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "shell.pid")


def running_pid():
    """PID of the running shell, or None (ignores a stale pidfile)."""
    try:
        with open(PIDFILE) as f:
            pid = int(f.read())
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return pid if b"main.py" in f.read() else None
    except (OSError, ValueError):
        return None


def volume_key(action):
    """Without GTK, so held keys stay fast. Mirrors VolItem: changing unmutes, muted counts as 0."""
    def pactl(*args):
        return subprocess.run(["pactl", *args], capture_output=True, text=True).stdout
    if action == "mute":
        pactl("set-sink-mute", "@DEFAULT_SINK@", "toggle")
        return
    muted = "yes" in pactl("get-sink-mute", "@DEFAULT_SINK@")
    m = re.search(r"(\d+)%", pactl("get-sink-volume", "@DEFAULT_SINK@"))
    shown = 0 if muted or not m else int(m.group(1))
    if muted:
        pactl("set-sink-mute", "@DEFAULT_SINK@", "0")
    pactl("set-sink-volume", "@DEFAULT_SINK@", f"{max(0, min(100, shown + (5 if action == 'up' else -5)))}%")


def on_signal(signum, handler):
    import gi
    from gi.repository import GLib
    try:
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signum, handler)
    except (ImportError, ValueError):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, handler)


def main():
    commands = {"--menu": signal.SIGUSR1, "--reload": signal.SIGHUP}
    if len(sys.argv) == 2 and sys.argv[1] in commands:
        pid = running_pid()
        if pid is None:
            sys.exit("shell is not running")
        os.kill(pid, commands[sys.argv[1]])
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--volume" and sys.argv[2] in ("up", "down", "mute"):
        volume_key(sys.argv[2])
        return

    # GTK is only loaded here: `--menu` above must start fast
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    from desktop import Desktop
    from taskbar import Taskbar

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    locale.setlocale(locale.LC_ALL, "")  # clock in the user's language
    bar = Taskbar()  # first: it loads the CSS
    Desktop().show_all()
    bar.connect("destroy", Gtk.main_quit)
    bar.show_all()
    on_signal(signal.SIGUSR1, lambda: bar.start.toggle_menu() or True)
    # exec in place: same PID, so the pidfile stays valid
    on_signal(signal.SIGHUP, lambda: os.execv(sys.executable, [sys.executable, os.path.realpath(__file__)]))
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))
    try:
        Gtk.main()
    finally:
        if running_pid() == os.getpid():
            os.remove(PIDFILE)


if __name__ == "__main__":
    main()
