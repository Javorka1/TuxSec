#!/usr/bin/env bash
# Generates a pre-compiled portable .tar.gz bundle ready to upload to GitHub Releases or send to friends.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOP="$(dirname "$HERE")"
OUT_DIR="$TOP/dist"
STAGE="$OUT_DIR/parsec-linux-host-x86_64"
ARCHIVE="$OUT_DIR/parsec-linux-host-x86_64.tar.gz"

if [ ! -x "$TOP/target/release/lowlatd" ] && [ ! -x "$TOP/bin/lowlatd" ]; then
    echo "Compilando lowlatd em modo release..."
    cargo build --release --bin lowlatd --manifest-path "$TOP/Cargo.toml"
fi

BIN_SRC="$TOP/target/release/lowlatd"
if [ ! -x "$BIN_SRC" ]; then
    BIN_SRC="$TOP/bin/lowlatd"
fi

rm -rf "$STAGE"
mkdir -p "$STAGE/target/release" "$STAGE/bin" "$STAGE/scripts" "$STAGE/packaging"

cp -f "$BIN_SRC" "$STAGE/target/release/lowlatd"
cp -f "$BIN_SRC" "$STAGE/bin/lowlatd"
cp -f "$TOP/scripts/kessel-login.py" "$STAGE/scripts/kessel-login.py"
cp -f "$TOP/scripts/lowlat-gui.py" "$STAGE/scripts/lowlat-gui.py"
cp -f "$TOP/scripts/lowlat-audio-guard.py" "$STAGE/scripts/lowlat-audio-guard.py"
cp -f "$TOP/packaging/install.sh" "$STAGE/packaging/install.sh"
cp -f "$TOP/packaging/tuxsec.png" "$STAGE/packaging/tuxsec.png"
cp -f "$TOP/packaging/lowlatd.service" "$STAGE/packaging/lowlatd.service"
cp -f "$TOP/packaging/lowlat-session.service" "$STAGE/packaging/lowlat-session.service"
cp -f "$TOP/packaging/lowlat-tray.service" "$STAGE/packaging/lowlat-tray.service"
cp -f "$TOP/packaging/lowlat-audio-guard.service" "$STAGE/packaging/lowlat-audio-guard.service"
cp -f "$TOP/packaging/lowlat-gui.desktop" "$STAGE/packaging/lowlat-gui.desktop"
cp -f "$TOP/packaging/70-lowlat-pads.rules" "$STAGE/packaging/70-lowlat-pads.rules"
cp -f "$TOP/packaging/sddm-10-wayland.conf.example" "$STAGE/packaging/sddm-10-wayland.conf.example"
cp -f "$TOP/README.md" "$STAGE/README.md"
cp -f "$TOP/install-linux.sh" "$STAGE/install-linux.sh"
if [ -f "$TOP/TuxSec" ]; then
    cp -f "$TOP/TuxSec" "$STAGE/TuxSec"
    chmod +x "$STAGE/TuxSec"
fi

# Create a clean template lowlatd.env WITHOUT personal session tokens!
cat > "$STAGE/packaging/lowlatd.env" << 'EOF'
# TuxSec / Parsec Linux Host Configuration
KESSEL_SESSION=
PULSE_SERVER=unix:/run/user/1000/pulse/native
LOWLATD_ARGS=--no-host-mute --approve-shared --clipboard both
EOF

chmod +x "$STAGE/install-linux.sh" "$STAGE/packaging/install.sh" \
    "$STAGE/scripts/lowlat-gui.py" "$STAGE/scripts/lowlat-audio-guard.py" "$STAGE/scripts/kessel-login.py"

tar -C "$OUT_DIR" -czf "$ARCHIVE" "parsec-linux-host-x86_64"
echo "✅ Pacote portátil gerado em: $ARCHIVE"
