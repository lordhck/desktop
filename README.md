# desktop

A small desktop shell for Xfce, written in Python and GTK 3: a taskbar with a Start menu,
grouped and pinned apps, a network indicator with a Wi-Fi popup, a clock, power options
and the desktop itself (wallpaper and right-click menu). It runs on xfwm4 in place of
xfce4-panel and xfdesktop.

The idea is to bring a tiny desktop to a server distro. It's built on Ubuntu Server,
chosen because nothing extra is installed: every package is one you picked.

## Requirements

    sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-wnck-3.0 librsvg2-common \
        xfwm4 xfce4-session xfce4-settings xfce4-terminal thunar network-manager libnotify-bin \
        qrencode xcape rofi

- `gir1.2-wnck-3.0`: window list for the taskbar
- `librsvg2-common`: loads the SVG icons
- `xfce4-session`: log out and lock screen
- `xfce4-settings`, `xfce4-terminal`, `thunar`: Settings, terminal and file manager in the desktop's
  right-click menu
- `network-manager`: Wi-Fi through `nmcli`
- `libnotify-bin`: connection notifications (`notify-send`)
- `qrencode`: QR code for sharing Wi-Fi
- `xcape`: opens the Start menu on a Super tap
- `rofi`: app search, themed by `rofi.rasi`

## Usage

    ./main.py           start the shell
    ./main.py --menu    open/close the Start menu
    ./main.py --reload  restart the running shell after code changes
    ./settings.py       Control Panel (also Start > Settings and the desktop's right-click menu)

To open the Start menu with Super, make a Super tap send Alt+F1 and bind Alt+F1 to
`main.py --menu` in Xfce's keyboard shortcuts:

    xcape -e 'Super_L=Alt_L|F1'

Search (apps, like Spotlight) is rofi with the shell's theme. Install its
icon once, then bind Super+Space to the rofi command:

    ln -s ~/dev/desktop/icons/search.svg ~/.local/share/icons/hicolor/scalable/actions/desktop-search.svg
    rofi -show drun -theme ~/dev/desktop/rofi.rasi
