# desktop

A small desktop shell for Xfce, written in Python and GTK 3: a taskbar with a Start menu,
grouped and pinned apps, a network indicator with a Wi-Fi popup, a clock and power options.
It runs on xfwm4 in place of xfce4-panel.

## Requirements

    sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-wnck-3.0 librsvg2-common \
        xfwm4 xfce4-session network-manager libnotify-bin qrencode xcape

- `gir1.2-wnck-3.0`: window list for the taskbar
- `librsvg2-common`: loads the SVG icons
- `xfce4-session`: log out and lock screen
- `network-manager`: Wi-Fi through `nmcli`
- `libnotify-bin`: connection notifications (`notify-send`)
- `qrencode`: QR code for sharing Wi-Fi
- `xcape`: opens the Start menu on a Super tap

## Usage

    ./main.py           start the shell
    ./main.py --menu    open/close the Start menu
    ./main.py --reload  restart the running shell after code changes

To open the Start menu with Super, make a Super tap send Alt+F1 and bind Alt+F1 to
`main.py --menu` in Xfce's keyboard shortcuts:

    xcape -e 'Super_L=Alt_L|F1'
