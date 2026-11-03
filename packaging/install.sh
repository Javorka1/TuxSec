#!/bin/sh
# Install TuxSec / lowlatd system-wide.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
top=$(dirname "$here")
dest=${DESTDIR:-}
if [ -x "$top/target/release/lowlatd" ]; then
    binary="$top/target/release/lowlatd"
elif [ -x "$top/bin/lowlatd" ]; then
    binary="$top/bin/lowlatd"
else
    binary="$top/target/release/lowlatd"
fi
env_file=/etc/lowlat/lowlatd.env

files() {
    cat <<EOF
/usr/bin/lowlatd 755 $binary
/usr/bin/lowlat-login 755 $top/scripts/kessel-login.py
/usr/bin/lowlat-gui 755 $top/scripts/lowlat-gui.py
/usr/bin/tuxsec 755 $top/scripts/lowlat-gui.py
/usr/bin/lowlat-audio-guard 755 $top/scripts/lowlat-audio-guard.py
/usr/share/pixmaps/tuxsec.png 644 $here/tuxsec.png
/usr/share/icons/hicolor/512x512/apps/tuxsec.png 644 $here/tuxsec.png
/usr/share/applications/lowlat-gui.desktop 644 $here/lowlat-gui.desktop
/usr/lib/systemd/system/lowlatd.service 644 $here/lowlatd.service
/usr/lib/systemd/user/lowlat-session.service 644 $here/lowlat-session.service
/usr/lib/systemd/user/lowlat-tray.service 644 $here/lowlat-tray.service
/usr/lib/systemd/user/lowlat-audio-guard.service 644 $here/lowlat-audio-guard.service
/usr/lib/udev/rules.d/70-lowlat-pads.rules 644 $here/70-lowlat-pads.rules
/usr/share/doc/lowlat/sddm-10-wayland.conf.example 644 $here/sddm-10-wayland.conf.example
/usr/share/doc/lowlat/README.md 644 $top/README.md
EOF
}

install_all() {
    if [ ! -x "$binary" ]; then
        echo "install: $binary is missing; build it first: cargo build --release -p lowlatd" >&2
        exit 1
    fi
    command -v python3 >/dev/null 2>&1 || echo "install: python3 is missing, and lowlat-login needs it" >&2
    files | while read -r to mode from; do
        install -D -m "$mode" "$from" "$dest$to"
    done
    if [ ! -e "$dest$env_file" ]; then
        install -D -m 640 "$here/lowlatd.env" "$dest$env_file"
    fi
    [ -z "$dest" ] || return 0
    systemctl daemon-reload
    systemctl enable lowlatd.service
    systemctl restart lowlatd.service
    systemctl --global enable lowlat-session.service lowlat-tray.service
    udevadm control --reload-rules 2>/dev/null || true
    echo "tuxsec/lowlat: instalado com sucesso!"
}

uninstall_all() {
    if [ -z "$dest" ]; then
        systemctl disable --now lowlatd.service 2>/dev/null || true
        systemctl --global disable lowlat-session.service lowlat-tray.service 2>/dev/null || true
    fi
    files | while read -r to mode from; do
        rm -f "$dest$to"
    done
    rmdir "$dest/usr/share/doc/lowlat" 2>/dev/null || true
    [ -z "$dest" ] || return 0
    systemctl daemon-reload
    udevadm control --reload-rules 2>/dev/null || true
    echo "lowlat: removed; $env_file is kept, and it carries the login's session"
}

case "${1:-}" in
    "") action=install_all ;;
    --uninstall) action=uninstall_all ;;
    *)
        echo "usage: $0 [--uninstall]" >&2
        exit 2
        ;;
esac
if [ -z "$dest" ] && [ "$(id -u)" -ne 0 ]; then
    echo "install: run it as root (sudo), or stage it with DESTDIR=..." >&2
    exit 1
fi
$action
