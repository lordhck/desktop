"""The few X11 calls GTK doesn't expose to Python."""
import ctypes

_xlib = ctypes.cdll.LoadLibrary("libX11.so.6")
_xlib.XOpenDisplay.restype = ctypes.c_void_p
_xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
_xlib.XInternAtom.restype = ctypes.c_ulong
_xlib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
_xlib.XChangeProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
_xlib.XFlush.argtypes = [ctypes.c_void_p]

XA_CARDINAL = 6
PROP_MODE_REPLACE = 0

_display = None


def _dpy():
    global _display
    if _display is None:
        _display = _xlib.XOpenDisplay(None)
    return _display


def _set_cardinals(xid, name, values):
    dpy = _dpy()
    atom = _xlib.XInternAtom(dpy, name.encode(), 0)
    data = (ctypes.c_long * len(values))(*values)
    _xlib.XChangeProperty(dpy, xid, atom, XA_CARDINAL, 32, PROP_MODE_REPLACE, data, len(values))
    _xlib.XFlush(dpy)


def reserve_bottom(xid, height, x_start, x_end):
    """Keep maximized windows above a bar of `height` px at the bottom of the screen."""
    _set_cardinals(xid, "_NET_WM_STRUT", [0, 0, 0, height])
    _set_cardinals(xid, "_NET_WM_STRUT_PARTIAL",
                   [0, 0, 0, height, 0, 0, 0, 0, 0, 0, x_start, x_end])
