#!/usr/bin/env bash
# Universal Installer for TuxSec — Parsec Linux Host (lowlat + GUI Control Panel + PipeWire Anti-Echo)
# Supports: Arch / CachyOS / Manjaro, Debian / Ubuntu / Pop!_OS / Mint, Fedora / Nobara
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_ID="$(id -u)"
USER_NAME="$(id -un)"

if [ "$USER_ID" -eq 0 ]; then
    echo "Execute este script como seu usuário normal (não use sudo diretamente)."
    echo "O script pedirá sudo apenas nas etapas de sistema."
    exit 1
fi

echo "============================================================"
echo "  🐧 TuxSec — Instalador do Parsec Linux Host com Interface"
echo "============================================================"

install_deps() {
    if command -v pacman >/dev/null 2>&1; then
        echo "[1/4] Detectado Arch Linux / CachyOS. Instalando dependências..."
        sudo pacman -S --needed --noconfirm \
            python python-pyqt6 pipewire libpulse vulkan-icd-loader polkit base-devel
    elif command -v apt-get >/dev/null 2>&1; then
        echo "[1/4] Detectado Debian / Ubuntu. Instalando dependências..."
        sudo apt-get update
        sudo apt-get install -y \
            python3 python3-pyqt6 pipewire-bin pulseaudio-utils libpulse0 \
            libvulkan1 libdrm2 policykit-1 build-essential pkg-config
    elif command -v dnf >/dev/null 2>&1; then
        echo "[1/4] Detectado Fedora / Nobara. Instalando dependências..."
        sudo dnf install -y \
            python3 python3-pyqt6 pipewire-utils pulseaudio-libs vulkan-loader \
            libdrm polkit gcc make
    else
        echo "[1/4] Distribuição genérica detectada. Certifique-se de ter Python3 + PyQt6 + PipeWire instalados."
    fi
}

build_if_needed() {
    if [ -x "$HERE/target/release/lowlatd" ] || [ -x "$HERE/bin/lowlatd" ]; then
        echo "[2/4] Executável pré-compilado 'lowlatd' encontrado na pasta! Pulando compilação."
        return
    fi
    echo "[2/4] Compilando o daemon 'lowlatd' (Rust)..."
    if ! command -v cargo >/dev/null 2>&1; then
        echo "Cargo/Rust não encontrado. Instalando via rustup..."
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
        # shellcheck disable=SC1091
        source "$HOME/.cargo/env"
    fi
    cargo build --release --bin lowlatd --manifest-path "$HERE/Cargo.toml"
}

install_files() {
    echo "[3/4] Instalando serviços, ícone TuxSec e painel gráfico no sistema..."
    sudo "$HERE/packaging/install.sh"
    sudo sed -i "s|^#* *PULSE_SERVER=.*|PULSE_SERVER=unix:/run/user/${USER_ID}/pulse/native|" /etc/lowlat/lowlatd.env || true
    if ! sudo grep -q "^PULSE_SERVER=" /etc/lowlat/lowlatd.env 2>/dev/null; then
        echo "PULSE_SERVER=unix:/run/user/${USER_ID}/pulse/native" | sudo tee -a /etc/lowlat/lowlatd.env >/dev/null
    fi
    sudo systemctl restart lowlatd.service

    echo "[4/4] Ativando serviços de sessão do usuário ($USER_NAME)..."
    systemctl --user daemon-reload || true
    systemctl --user enable --now lowlat-session.service lowlat-tray.service lowlat-audio-guard.service || true
}

install_deps
build_if_needed
install_files

echo ""
echo "✅ Instalação do TuxSec concluída com sucesso!"
echo "   • Abrindo o Painel de Controle TuxSec..."
echo "   • Clique em '🔑 Conta Parsec' no topo do painel para fazer login!"
nohup /usr/bin/lowlat-gui >/dev/null 2>&1 &
