#!/usr/bin/env python3
"""Parsec Linux Host — Native Qt6 Control Panel for lowlatd."""

import json
import os
import shlex
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

SOCKET_PATH = "/run/lowlatd/session"
ENV_FILE = Path("/etc/lowlat/lowlatd.env")
AUDIO_GUARD_CFG = Path.home() / ".config" / "lowlat" / "audio-guard.json"
DEFAULT_BLOCKED_APPS = ["webrtc voiceengine", "discord", "vesktop", "equibop", "teamspeak", "mumble"]
SYSTEM_AUDIO_PREFIXES = (
    "alsa_output.",
    "alsa_input.",
    "bluez_output.",
    "bluez_input.",
    "midi-bridge",
    "bluez_midi",
    "lowlat",
)
MAX_FRAME = 1 << 20

STYLE_SHEET = """
QMainWindow, QWidget#central {
    background-color: #111217;
    color: #f0f2f8;
    font-family: 'Inter', 'Noto Sans', sans-serif;
    font-size: 13px;
}
QFrame.card {
    background-color: #1a1c24;
    border: 1px solid #282c3a;
    border-radius: 12px;
}
QFrame.guest-row {
    background-color: #222530;
    border: 1px solid #2f3446;
    border-radius: 10px;
}
QLabel.header-title {
    font-size: 20px;
    font-weight: 700;
    color: #ffffff;
}
QLabel.section-title {
    font-size: 15px;
    font-weight: 700;
    color: #e2e6f3;
}
QLabel.muted {
    color: #949bb0;
    font-size: 12px;
}
QLabel.badge-online {
    background-color: #163829;
    color: #34d399;
    border: 1px solid #059669;
    border-radius: 10px;
    padding: 4px 10px;
    font-weight: 600;
}
QLabel.badge-offline {
    background-color: #3b1c24;
    color: #f87171;
    border: 1px solid #dc2626;
    border-radius: 10px;
    padding: 4px 10px;
    font-weight: 600;
}
QLabel.badge-role {
    background-color: #2d2346;
    color: #c084fc;
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton {
    background-color: #262936;
    color: #e2e6f3;
    border: 1px solid #353a4d;
    border-radius: 8px;
    padding: 7px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #313546;
    border-color: #4a516b;
}
QPushButton.primary {
    background-color: #8b5cf6;
    color: #ffffff;
    border: 1px solid #7c3aed;
}
QPushButton.primary:hover {
    background-color: #7c3aed;
}
QPushButton.active-pill {
    background-color: #8b5cf6;
    color: #ffffff;
    border: 1px solid #a78bfa;
}
QPushButton.perm-on {
    background-color: #163829;
    color: #34d399;
    border: 1px solid #059669;
    padding: 5px 10px;
}
QPushButton.perm-off {
    background-color: #262936;
    color: #7e859a;
    border: 1px solid #353a4d;
    padding: 5px 10px;
}
QPushButton.danger {
    background-color: #3b1c24;
    color: #f87171;
    border: 1px solid #991b1b;
    padding: 5px 12px;
}
QPushButton.danger:hover {
    background-color: #7f1d1d;
    color: #ffffff;
}
QComboBox, QSpinBox, QLineEdit {
    background-color: #14161d;
    color: #f0f2f8;
    border: 1px solid #32374a;
    border-radius: 7px;
    padding: 6px 10px;
    min-height: 20px;
}
QCheckBox {
    color: #d5d9e8;
    spacing: 8px;
}
"""


class DaemonBridge(QObject):
    state_changed = pyqtSignal(bool, dict)

    def __init__(self):
        super().__init__()
        self._sock = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _recv_exact(self, sock, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise EOFError("Socket closed")
            buf.extend(chunk)
        return bytes(buf)

    def _recv_frame(self, sock):
        size = struct.unpack("<I", self._recv_exact(sock, 4))[0]
        if size > MAX_FRAME:
            raise ValueError("Frame too large")
        return json.loads(self._recv_exact(sock, size))

    def _send_frame(self, sock, payload):
        raw = json.dumps(payload).encode("utf-8")
        sock.sendall(struct.pack("<I", len(raw)) + raw)

    def send(self, payload):
        with self._lock:
            if self._sock is None:
                raise ConnectionError("O serviço lowlatd não está conectado.")
            self._send_frame(self._sock, payload)

    def _run(self):
        while not self._stop.is_set():
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.settimeout(2.0)
                    sock.connect(SOCKET_PATH)
                    self._send_frame(sock, {"version": 1, "role": "tray", "can": []})
                    sock.settimeout(None)
                    with self._lock:
                        self._sock = sock
                    self.state_changed.emit(True, {})
                    while not self._stop.is_set():
                        msg = self._recv_frame(sock)
                        if isinstance(msg, dict) and isinstance(msg.get("state"), dict):
                            self.state_changed.emit(True, msg["state"])
            except Exception:
                pass
            finally:
                with self._lock:
                    self._sock = None
                self.state_changed.emit(False, {})
            self._stop.wait(1.5)


def discover_local_outputs():
    outputs = []
    seen = set()
    try:
        res = subprocess.run(
            ["/usr/bin/lowlatd", "--outputs"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        for line in res.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and ":" in parts[0]:
                out_id = parts[0]
                connector = out_id.split(":", 1)[1]
                res_str = parts[1]
                outputs.append({"id": out_id, "connector": connector, "res": res_str})
                seen.add(out_id)
    except Exception:
        pass

    # Fallback: read connected DRM outputs from /sys/class/drm so any GPU/connector
    # (HDMI, DP, eDP, DVI, VGA, Virtual) appears even without root DRM master access
    try:
        for status_path in sorted(Path("/sys/class/drm").glob("card*-*/status")):
            if status_path.read_text().strip() != "connected":
                continue
            dir_name = status_path.parent.name  # e.g. card1-HDMI-A-1
            if "-" not in dir_name:
                continue
            card, connector = dir_name.split("-", 1)
            out_id = f"{card}:{connector}"
            if out_id in seen:
                continue
            res_str = ""
            modes_file = status_path.parent / "modes"
            if modes_file.exists():
                modes = [m.strip() for m in modes_file.read_text().splitlines() if m.strip()]
                if modes:
                    res_str = modes[0]
            outputs.append({"id": out_id, "connector": connector, "res": res_str})
            seen.add(out_id)
    except Exception:
        pass

    return outputs


def parse_lowlatd_env():
    cfg = {
        "output": "",
        "codec": "h264",
        "fps": 60,
        "bitrate": 20,
        "clipboard": "both",
        "no_host_mute": True,
        "approve_shared": True,
        "name": socket.gethostname(),
    }
    try:
        if not ENV_FILE.exists():
            return cfg
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("LOWLATD_ARGS="):
                raw = line[len("LOWLATD_ARGS=") :].strip()
                tokens = shlex.split(raw)
                i = 0
                cfg["no_host_mute"] = "--no-host-mute" in tokens
                cfg["approve_shared"] = "--approve-shared" in tokens
                while i < len(tokens):
                    t = tokens[i]
                    if t == "--output" and i + 1 < len(tokens):
                        cfg["output"] = tokens[i + 1]
                        i += 2
                    elif t == "--codec" and i + 1 < len(tokens):
                        cfg["codec"] = tokens[i + 1]
                        i += 2
                    elif t == "--fps" and i + 1 < len(tokens):
                        try:
                            cfg["fps"] = int(tokens[i + 1])
                        except ValueError:
                            pass
                        i += 2
                    elif t == "--bitrate" and i + 1 < len(tokens):
                        try:
                            cfg["bitrate"] = int(float(tokens[i + 1]))
                        except ValueError:
                            pass
                        i += 2
                    elif t == "--clipboard" and i + 1 < len(tokens):
                        cfg["clipboard"] = tokens[i + 1]
                        i += 2
                    elif t == "--name" and i + 1 < len(tokens):
                        cfg["name"] = tokens[i + 1]
                        i += 2
                    else:
                        i += 1
    except Exception:
        pass
    return cfg


def find_app_icon_path():
    candidates = [
        Path(__file__).resolve().parent.parent / "packaging" / "tuxsec.png",
        Path(__file__).resolve().parent.parent / "tuxsec.png",
        Path("/usr/share/pixmaps/tuxsec.png"),
        Path("/usr/share/icons/hicolor/512x512/apps/tuxsec.png"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return ""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TuxSec — Parsec Linux Host")
        icon_path = find_app_icon_path()
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))
        else:
            self.setWindowIcon(QIcon.fromTheme("video-display"))
        self.resize(820, 720)
        self.setStyleSheet(STYLE_SHEET)

        self.online = False
        self.state = {}
        self.local_outputs = discover_local_outputs()

        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(20, 20, 20, 20)
        root_layout.setSpacing(16)

        # Header
        header = QHBoxLayout()
        if icon_path:
            logo_lbl = QLabel()
            pix = QPixmap(icon_path)
            if not pix.isNull():
                logo_lbl.setPixmap(
                    pix.scaled(52, 52, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                )
                header.addWidget(logo_lbl)
                header.addSpacing(8)

        title_box = QVBoxLayout()
        self.title_lbl = QLabel(f"TuxSec Host • {socket.gethostname()}")
        self.title_lbl.setProperty("class", "header-title")
        self.sub_lbl = QLabel("Gerenciamento em tempo real de tela, taxa de bits e convidados conectados")
        self.sub_lbl.setProperty("class", "muted")
        title_box.addWidget(self.title_lbl)
        title_box.addWidget(self.sub_lbl)
        header.addLayout(title_box)
        header.addStretch()

        self.badge_lbl = QLabel("● Conectando ao serviço...")
        self.badge_lbl.setProperty("class", "badge-offline")
        header.addWidget(self.badge_lbl)

        self.btn_login = QPushButton("🔑 Conta Parsec")
        self.btn_login.setProperty("class", "primary")
        self.btn_login.clicked.connect(self.open_login_dialog)
        header.addWidget(self.btn_login)

        self.btn_toggle_service = QPushButton("Reiniciar Host")
        self.btn_toggle_service.clicked.connect(self.restart_service)
        header.addWidget(self.btn_toggle_service)
        root_layout.addLayout(header)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("central")
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 0, 4, 0)
        self.content_layout.setSpacing(16)
        scroll.setWidget(content)
        root_layout.addWidget(scroll)

        self._build_live_card()
        self._build_guests_card()
        self._build_audio_guard_card()
        self._build_defaults_card()
        self.content_layout.addStretch()

        # Status bar message
        self.status_msg = QLabel("Pronto.")
        self.status_msg.setProperty("class", "muted")
        root_layout.addWidget(self.status_msg)

        self.bridge = DaemonBridge()
        self.bridge.state_changed.connect(self.on_state_changed)

        self.audio_timer = QTimer(self)
        self.audio_timer.timeout.connect(self.refresh_audio_guard)
        self.audio_timer.start(1200)
        self.refresh_audio_guard()

    def notify_msg(self, text):
        self.status_msg.setText(text)

    def _build_live_card(self):
        card = QFrame()
        card.setProperty("class", "card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        top = QHBoxLayout()
        lbl = QLabel("🖥️  Transmissão Ao Vivo (Troca Instantânea)")
        lbl.setProperty("class", "section-title")
        top.addWidget(lbl)
        top.addStretch()
        self.live_summary = QLabel("Nenhuma transmissão ativa no momento")
        self.live_summary.setProperty("class", "muted")
        top.addWidget(self.live_summary)
        layout.addLayout(top)

        # Monitor buttons row
        mon_row = QHBoxLayout()
        mon_lbl = QLabel("Monitor Ativo:")
        mon_lbl.setMinimumWidth(120)
        mon_row.addWidget(mon_lbl)
        self.mon_btn_container = QHBoxLayout()
        self.mon_btn_container.setSpacing(10)
        mon_row.addLayout(self.mon_btn_container)
        mon_row.addStretch()
        layout.addLayout(mon_row)
        self._populate_monitor_buttons([])

        # FPS buttons row
        fps_row = QHBoxLayout()
        fps_lbl = QLabel("Taxa de Quadros:")
        fps_lbl.setMinimumWidth(120)
        fps_row.addWidget(fps_lbl)
        self.fps_buttons = {}
        for fps in (30, 60, 120, 144):
            btn = QPushButton(f"{fps} FPS")
            btn.clicked.connect(lambda _, f=fps: self.set_live_fps(f))
            fps_row.addWidget(btn)
            self.fps_buttons[fps] = btn
        fps_row.addStretch()
        layout.addLayout(fps_row)

        # Bitrate row
        br_row = QHBoxLayout()
        br_lbl = QLabel("Bitrate Máximo:")
        br_lbl.setMinimumWidth(120)
        br_row.addWidget(br_lbl)
        self.br_buttons = {}
        for mbps in (10, 20, 35, 50, 80):
            btn = QPushButton(f"{mbps} Mbps")
            btn.clicked.connect(lambda _, m=mbps: self.set_live_bitrate(m))
            br_row.addWidget(btn)
            self.br_buttons[mbps] = btn
        br_row.addStretch()
        layout.addLayout(br_row)

        self.content_layout.addWidget(card)

    def _populate_monitor_buttons(self, daemon_outputs):
        while self.mon_btn_container.count():
            item = self.mon_btn_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        outputs = daemon_outputs if daemon_outputs else self.local_outputs
        active_conn = self.state.get("output", "")
        active_id = self.state.get("output_id", "")

        auto_btn = QPushButton("✨ Automático")
        if not active_conn and not active_id:
            auto_btn.setProperty("class", "active-pill")
        auto_btn.clicked.connect(lambda: self.set_live_output("none"))
        self.mon_btn_container.addWidget(auto_btn)

        for idx, out in enumerate(outputs):
            out_id = out.get("id", "")
            conn = out.get("connector", out_id)
            width = out.get("width", "")
            height = out.get("height", "")
            res = f"{width}x{height}" if width and height else out.get("res", "")
            label = f"{conn} ({res})" if res else conn
            if len(outputs) == 1 or (out.get("x") == 0 and out.get("y") == 0 and "x" in out):
                label = f"★ {label} [Principal]"
            elif len(outputs) > 1:
                label = f"🖥️ {label} [Monitor {idx + 1}]"

            btn = QPushButton(label)
            is_active = (conn == active_conn and active_conn != "") or (out_id == active_id and active_id != "")
            if is_active:
                btn.setProperty("class", "active-pill")
            btn.clicked.connect(lambda _, oid=out_id: self.set_live_output(oid))
            self.mon_btn_container.addWidget(btn)

    def _build_guests_card(self):
        card = QFrame()
        card.setProperty("class", "card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        top = QHBoxLayout()
        lbl = QLabel("👥  Convidados Conectados & Permissões")
        lbl.setProperty("class", "section-title")
        top.addWidget(lbl)
        top.addStretch()
        self.guests_count_lbl = QLabel("0 conectados")
        self.guests_count_lbl.setProperty("class", "muted")
        top.addWidget(self.guests_count_lbl)
        layout.addLayout(top)

        self.guests_box = QVBoxLayout()
        self.guests_box.setSpacing(10)
        layout.addLayout(self.guests_box)

        self.content_layout.addWidget(card)

    def _load_audio_guard_cfg(self):
        cfg = {"enabled": True, "blocked": list(DEFAULT_BLOCKED_APPS)}
        try:
            if AUDIO_GUARD_CFG.exists():
                data = json.loads(AUDIO_GUARD_CFG.read_text())
                if isinstance(data, dict):
                    cfg["enabled"] = bool(data.get("enabled", True))
                    if isinstance(data.get("blocked"), list):
                        cfg["blocked"] = [str(x).strip().lower() for x in data["blocked"] if str(x).strip()]
        except Exception:
            pass
        return cfg

    def _save_audio_guard_cfg(self, cfg):
        try:
            AUDIO_GUARD_CFG.parent.mkdir(parents=True, exist_ok=True)
            AUDIO_GUARD_CFG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
        except Exception:
            pass

    def _build_audio_guard_card(self):
        card = QFrame()
        card.setProperty("class", "card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        top = QHBoxLayout()
        lbl = QLabel("🔇  Isolamento de Áudio Automático (Anti-Eco Discord / PipeWire)")
        lbl.setProperty("class", "section-title")
        top.addWidget(lbl)
        top.addStretch()
        self.audio_guard_status = QLabel("Ativo")
        self.audio_guard_status.setProperty("class", "muted")
        top.addWidget(self.audio_guard_status)
        layout.addLayout(top)

        cfg = self._load_audio_guard_cfg()
        self.chk_audio_guard = QCheckBox(
            "Bloquear automaticamente o áudio do Discord/Voz no stream (sem precisar ir no Graph)"
        )
        self.chk_audio_guard.setChecked(cfg["enabled"])
        self.chk_audio_guard.toggled.connect(self.toggle_audio_guard_enabled)
        layout.addWidget(self.chk_audio_guard)

        self.audio_apps_box = QVBoxLayout()
        self.audio_apps_box.setSpacing(8)
        layout.addLayout(self.audio_apps_box)

        self.content_layout.addWidget(card)

    def toggle_audio_guard_enabled(self, checked):
        cfg = self._load_audio_guard_cfg()
        cfg["enabled"] = bool(checked)
        self._save_audio_guard_cfg(cfg)
        self.refresh_audio_guard()
        self.notify_msg(
            "Isolamento automático do Discord ATIVADO."
            if checked
            else "Isolamento automático DESATIVADO (capturando todo o monitor de áudio)."
        )

    def toggle_app_audio_block(self, app_name, currently_blocked):
        cfg = self._load_audio_guard_cfg()
        low = app_name.lower()
        if currently_blocked:
            cfg["blocked"] = [b for b in cfg["blocked"] if b not in low and low not in b]
        else:
            if low not in cfg["blocked"]:
                cfg["blocked"].append(low)
        self._save_audio_guard_cfg(cfg)
        self.refresh_audio_guard()
        self.notify_msg(
            f"Áudio de '{app_name}' {'LIBERADO para a transmissão' if currently_blocked else 'BLOQUEADO na transmissão'}."
        )

    def refresh_audio_guard(self):
        cfg = self._load_audio_guard_cfg()
        try:
            # Import and run enforce_once if available alongside script or in /usr/bin
            outputs = {}
            inputs = {}
            links = set()
            res_o = subprocess.run(["pw-link", "-Io"], capture_output=True, text=True, timeout=1.5)
            for line in res_o.stdout.splitlines():
                line = line.strip()
                if not line or ":" not in line:
                    continue
                parts = line.split(None, 1)
                if len(parts) == 2 and parts[0].isdigit():
                    pid = int(parts[0])
                    node, port = parts[1].rsplit(":", 1)
                    outputs[pid] = (node, port)

            res_i = subprocess.run(["pw-link", "-Ii"], capture_output=True, text=True, timeout=1.5)
            for line in res_i.stdout.splitlines():
                line = line.strip()
                if not line or ":" not in line:
                    continue
                parts = line.split(None, 1)
                if len(parts) == 2 and parts[0].isdigit():
                    pid = int(parts[0])
                    node, port = parts[1].rsplit(":", 1)
                    inputs[pid] = (node, port)

            res_l = subprocess.run(["pw-link", "-Il"], capture_output=True, text=True, timeout=1.5)
            current_port = None
            for line in res_l.stdout.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if "|->" in stripped:
                    rhs = stripped.split("|->", 1)[1].strip()
                    rparts = rhs.split(None, 1)
                    if current_port is not None and rparts and rparts[0].isdigit():
                        links.add((current_port, int(rparts[0])))
                elif "|<-" in stripped:
                    rhs = stripped.split("|<-", 1)[1].strip()
                    rparts = rhs.split(None, 1)
                    if current_port is not None and rparts and rparts[0].isdigit():
                        links.add((int(rparts[0]), current_port))
                else:
                    parts = stripped.split(None, 1)
                    if parts and parts[0].isdigit():
                        current_port = int(parts[0])

            lowlat_fl = None
            lowlat_fr = None
            for pid, (node, port) in inputs.items():
                if node == "lowlat":
                    if port == "input_FL":
                        lowlat_fl = pid
                    elif port == "input_FR":
                        lowlat_fr = pid

            def is_blocked(name):
                ln = name.lower()
                return any(pat and pat in ln for pat in cfg["blocked"])

            def is_sys(name):
                return name.lower().startswith(SYSTEM_AUDIO_PREFIXES)

            if lowlat_fl is not None and lowlat_fr is not None:
                if cfg["enabled"]:
                    for out_pid, in_pid in list(links):
                        if in_pid not in (lowlat_fl, lowlat_fr):
                            continue
                        info = outputs.get(out_pid)
                        if info and (info[1].startswith("monitor_") or is_sys(info[0]) or is_blocked(info[0])):
                            subprocess.run(["pw-link", "-d", str(out_pid), str(in_pid)], capture_output=True, timeout=1)
                            links.discard((out_pid, in_pid))
                    for out_pid, (node, port) in outputs.items():
                        if is_sys(node) or is_blocked(node):
                            continue
                        if port == "output_FL" and (out_pid, lowlat_fl) not in links:
                            subprocess.run(["pw-link", str(out_pid), str(lowlat_fl)], capture_output=True, timeout=1)
                            links.add((out_pid, lowlat_fl))
                        elif port == "output_FR" and (out_pid, lowlat_fr) not in links:
                            subprocess.run(["pw-link", str(out_pid), str(lowlat_fr)], capture_output=True, timeout=1)
                            links.add((out_pid, lowlat_fr))

            apps = {}
            for pid, (node, port) in outputs.items():
                if is_sys(node) or not port.startswith("output_"):
                    continue
                blk = is_blocked(node)
                lnk = (lowlat_fl is not None and (pid, lowlat_fl) in links) or (
                    lowlat_fr is not None and (pid, lowlat_fr) in links
                )
                prev = apps.get(node, {"blocked": blk, "linked": False})
                apps[node] = {"blocked": blk, "linked": prev["linked"] or lnk}

            self.audio_guard_status.setText(
                "● Filtrando áudio da transmissão" if lowlat_fl is not None else "○ Aguardando transmissão"
            )

            sig = json.dumps(apps, sort_keys=True) + str(cfg["enabled"])
            if getattr(self, "_last_audio_sig", None) == sig:
                return
            self._last_audio_sig = sig

            while self.audio_apps_box.count():
                item = self.audio_apps_box.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            if not apps:
                empty = QLabel("Nenhum aplicativo reproduzindo áudio no momento.")
                empty.setProperty("class", "muted")
                self.audio_apps_box.addWidget(empty)
            else:
                for app_name, info in sorted(apps.items()):
                    row = QFrame()
                    row.setProperty("class", "guest-row")
                    rl = QHBoxLayout(row)
                    rl.setContentsMargins(12, 8, 12, 8)
                    display_name = (
                        f"{app_name} (Discord / Voz)"
                        if "webrtc" in app_name.lower() or "discord" in app_name.lower()
                        else app_name
                    )
                    lbl = QLabel(f"🎵  {display_name}")
                    lbl.setStyleSheet("font-weight: 600;")
                    rl.addWidget(lbl)
                    rl.addStretch()

                    blk = info["blocked"]
                    btn = QPushButton(
                        "🔇 Bloqueado no Stream (Clique p/ liberar)"
                        if blk
                        else "🔊 Enviando pro Stream (Clique p/ bloquear)"
                    )
                    btn.setProperty("class", "danger" if blk else "perm-on")
                    btn.clicked.connect(lambda _, a=app_name, b=blk: self.toggle_app_audio_block(a, b))
                    rl.addWidget(btn)
                    self.audio_apps_box.addWidget(row)
        except Exception:
            pass

    def _build_defaults_card(self):
        card = QFrame()
        card.setProperty("class", "card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        lbl = QLabel("⚙️  Configurações Padrão de Inicialização (/etc/lowlat/lowlatd.env)")
        lbl.setProperty("class", "section-title")
        layout.addWidget(lbl)

        cfg = parse_lowlatd_env()

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Monitor Padrão:"))
        self.cmb_default_output = QComboBox()
        self.cmb_default_output.addItem("Automático", "")
        for out in self.local_outputs:
            oid = out.get("id", "")
            conn = out.get("connector", oid)
            res = out.get("res", "")
            self.cmb_default_output.addItem(f"{conn} ({res}) [{oid}]" if res else f"{conn} [{oid}]", oid)
        if self.cmb_default_output.findData(cfg["output"]) < 0 and cfg["output"]:
            self.cmb_default_output.addItem(cfg["output"], cfg["output"])
        idx = self.cmb_default_output.findData(cfg["output"])
        if idx >= 0:
            self.cmb_default_output.setCurrentIndex(idx)
        row1.addWidget(self.cmb_default_output, 1)

        row1.addSpacing(16)
        row1.addWidget(QLabel("Codec:"))
        self.cmb_codec = QComboBox()
        self.cmb_codec.addItem("HEVC / H.265 (Melhor Qualidade)", "hevc")
        self.cmb_codec.addItem("H.264 (Maior Compatibilidade)", "h264")
        c_idx = self.cmb_codec.findData(cfg["codec"])
        if c_idx >= 0:
            self.cmb_codec.setCurrentIndex(c_idx)
        row1.addWidget(self.cmb_codec, 1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Bitrate Inicial (Mbps):"))
        self.spn_bitrate = QSpinBox()
        self.spn_bitrate.setRange(2, 100)
        self.spn_bitrate.setValue(cfg["bitrate"])
        row2.addWidget(self.spn_bitrate)

        row2.addSpacing(16)
        row2.addWidget(QLabel("FPS Inicial:"))
        self.spn_fps = QSpinBox()
        self.spn_fps.setRange(30, 240)
        self.spn_fps.setValue(cfg["fps"])
        row2.addWidget(self.spn_fps)

        row2.addSpacing(16)
        row2.addWidget(QLabel("Clipboard:"))
        self.cmb_clip = QComboBox()
        self.cmb_clip.addItem("Ambos os lados (Host ↔ Convidado)", "both")
        self.cmb_clip.addItem("Apenas Convidado → Host", "send")
        self.cmb_clip.addItem("Desativado", "off")
        clip_idx = self.cmb_clip.findData(cfg["clipboard"])
        if clip_idx >= 0:
            self.cmb_clip.setCurrentIndex(clip_idx)
        row2.addWidget(self.cmb_clip, 1)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.chk_no_mute = QCheckBox("Manter som ligado no PC Linux enquanto transmite (--no-host-mute)")
        self.chk_no_mute.setChecked(cfg["no_host_mute"])
        row3.addWidget(self.chk_no_mute)

        self.chk_approve = QCheckBox("Aceitar conexão de amigos automaticamente (--approve-shared)")
        self.chk_approve.setChecked(cfg["approve_shared"])
        row3.addWidget(self.chk_approve)
        layout.addLayout(row3)

        btn_row = QHBoxLayout()
        btn_save = QPushButton("💾  Salvar Padrões e Reiniciar Host")
        btn_save.setProperty("class", "primary")
        btn_save.clicked.connect(self.save_persistent_settings)
        btn_row.addStretch()
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

        self.content_layout.addWidget(card)

    def set_live_output(self, output_id):
        try:
            self.bridge.send({"config": {"video": [{"output": output_id}]}})
            self.notify_msg(f"Monitor alterado em tempo real para {output_id}!")
        except Exception as e:
            self.notify_msg(f"Erro: {e}")

    def set_live_fps(self, fps):
        try:
            self.bridge.send({"config": {"video": [{"encoderFPS": fps}]}})
            self.notify_msg(f"Taxa de quadros alterada em tempo real para {fps} FPS!")
        except Exception as e:
            self.notify_msg(f"Erro: {e}")

    def set_live_bitrate(self, mbps):
        try:
            self.bridge.send({"config": {"video": [{"encoderMaxBitrate": mbps}]}})
            self.notify_msg(f"Bitrate máximo alterado em tempo real para {mbps} Mbps!")
        except Exception as e:
            self.notify_msg(f"Erro: {e}")

    def kick_guest(self, guest_id):
        try:
            self.bridge.send({"kick": guest_id})
            self.notify_msg(f"Convidado #{guest_id} desconectado.")
        except Exception as e:
            self.notify_msg(f"Erro: {e}")

    def toggle_permission(self, guest, field):
        gid = guest.get("id")
        perms = {
            "guest": gid,
            "gamepad": bool(guest.get("gamepad", True)),
            "keyboard": bool(guest.get("keyboard", False)),
            "mouse": bool(guest.get("mouse", False)),
        }
        perms[field] = not perms[field]
        try:
            self.bridge.send({"permissions": perms})
            self.notify_msg(
                f"Permissão '{field}' de {guest.get('name') or f'Guest #{gid}'} alterada para {'ATIVO' if perms[field] else 'BLOQUEADO'}."
            )
        except Exception as e:
            self.notify_msg(f"Erro: {e}")

    def on_state_changed(self, online, state):
        self.online = online
        if state:
            self.state = state

        if not online:
            self.badge_lbl.setText("○ HOST OFFLINE")
            self.badge_lbl.setProperty("class", "badge-offline")
            self.badge_lbl.style().unpolish(self.badge_lbl)
            self.badge_lbl.style().polish(self.badge_lbl)
            self.live_summary.setText("Serviço desconectado")
            return

        guests = self.state.get("guests", [])
        if guests:
            self.badge_lbl.setText(f"● TRANSMITINDO ({len(guests)} conectado(s))")
        else:
            self.badge_lbl.setText("● ONLINE — Aguardando Conexão")
        self.badge_lbl.setProperty("class", "badge-online")
        self.badge_lbl.style().unpolish(self.badge_lbl)
        self.badge_lbl.style().polish(self.badge_lbl)

        out_name = self.state.get("output") or "Automático"
        w = self.state.get("width", 0)
        h = self.state.get("height", 0)
        fps = self.state.get("fps", 0)
        br = self.state.get("bitrate", 0)
        codec = (self.state.get("codec") or "h264").upper()
        if w and h:
            self.live_summary.setText(f"{out_name} • {w}×{h} • {fps} FPS • {br} Mbps • {codec}")
        else:
            self.live_summary.setText(f"Monitor pronto ({out_name}) • Aguardando cliente iniciar vídeo")

        self._populate_monitor_buttons(self.state.get("outputs", []))

        for f_val, btn in self.fps_buttons.items():
            btn.setProperty("class", "active-pill" if fps == f_val else "")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        for b_val, btn in self.br_buttons.items():
            btn.setProperty("class", "active-pill" if br == b_val else "")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        # Render guests
        self.guests_count_lbl.setText(f"{len(guests)} conectado(s)")
        while self.guests_box.count():
            item = self.guests_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not guests:
            empty = QLabel("Nenhum convidado conectado no momento.")
            empty.setProperty("class", "muted")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.guests_box.addWidget(empty)
        else:
            for g in guests:
                row_frame = QFrame()
                row_frame.setProperty("class", "guest-row")
                rlay = QHBoxLayout(row_frame)
                rlay.setContentsMargins(14, 10, 14, 10)
                rlay.setSpacing(10)

                gid = g.get("id", 0)
                gname = g.get("name") or f"Guest #{gid}"
                is_owner = g.get("owner", False)
                is_conn = g.get("connected", False)

                name_lbl = QLabel(f"👤  {gname}")
                name_lbl.setStyleSheet("font-weight: 700; font-size: 14px;")
                rlay.addWidget(name_lbl)

                role_lbl = QLabel("DONO (Você)" if is_owner else "CONVIDADO")
                role_lbl.setProperty("class", "badge-role")
                rlay.addWidget(role_lbl)

                st_lbl = QLabel("• Conectado" if is_conn else "• Conectando...")
                st_lbl.setProperty("class", "muted")
                rlay.addWidget(st_lbl)
                rlay.addStretch()

                # Permissions toggles if supported by daemon
                if "gamepad" in g:
                    for key, icon, label in (
                        ("gamepad", "🎮", "Controle"),
                        ("keyboard", "⌨️", "Teclado"),
                        ("mouse", "🖱️", "Mouse"),
                    ):
                        on = bool(g.get(key, False))
                        pbtn = QPushButton(f"{icon} {label}: {'SIM' if on else 'NÃO'}")
                        pbtn.setProperty("class", "perm-on" if on else "perm-off")
                        pbtn.clicked.connect(lambda _, guest_obj=dict(g), k=key: self.toggle_permission(guest_obj, k))
                        rlay.addWidget(pbtn)

                kick_btn = QPushButton("🚫 Expulsar")
                kick_btn.setProperty("class", "danger")
                kick_btn.clicked.connect(lambda _, i=gid: self.kick_guest(i))
                rlay.addWidget(kick_btn)

                self.guests_box.addWidget(row_frame)

    def open_login_dialog(self):
        dlg = LoginDialog(self)
        dlg.exec()

    def restart_service(self):
        subprocess.Popen(["pkexec", "systemctl", "restart", "lowlatd.service"])
        self.notify_msg("Solicitando reinicialização do serviço lowlatd.service...")

    def save_persistent_settings(self):
        args = []
        out = self.cmb_default_output.currentData()
        if out:
            args += ["--output", out]
        codec = self.cmb_codec.currentData()
        if codec:
            args += ["--codec", codec]
        args += ["--bitrate", str(self.spn_bitrate.value())]
        args += ["--fps", str(self.spn_fps.value())]
        args += ["--clipboard", self.cmb_clip.currentData()]
        if self.chk_no_mute.isChecked():
            args.append("--no-host-mute")
        if self.chk_approve.isChecked():
            args.append("--approve-shared")

        args_line = "LOWLATD_ARGS=" + " ".join(args)
        uid = os.getuid()
        pulse_line = f"PULSE_SERVER=unix:/run/user/{uid}/pulse/native"

        script = (
            f"sed -i 's|^LOWLATD_ARGS=.*|{args_line}|' /etc/lowlat/lowlatd.env && "
            f"sed -i 's|^#* *PULSE_SERVER=.*|{pulse_line}|' /etc/lowlat/lowlatd.env && "
            "systemctl restart lowlatd.service"
        )
        subprocess.Popen(["pkexec", "/bin/sh", "-c", script])
        self.notify_msg("Salvando configurações em /etc/lowlat/lowlatd.env e reiniciando o Host...")


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Autenticação Parsec — Configurar Conta do Host")
        self.setMinimumWidth(460)
        self.setStyleSheet(STYLE_SHEET)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 22, 22, 22)
        lay.setSpacing(14)

        title = QLabel("🔑  Conectar Conta Parsec no Host Linux")
        title.setProperty("class", "section-title")
        lay.addWidget(title)

        desc = QLabel(
            "Entre com seu e-mail e senha do Parsec para registrar este PC Linux como Host.\n"
            "Se sua conta tiver 2FA ativo ou pedir confirmação de novo IP por e-mail, "
            "preencha o código 2FA abaixo."
        )
        desc.setWordWrap(True)
        desc.setProperty("class", "muted")
        lay.addWidget(desc)

        lay.addWidget(QLabel("E-mail da conta Parsec:"))
        self.inp_email = QLineEdit()
        self.inp_email.setPlaceholderText("seu-email@exemplo.com")
        lay.addWidget(self.inp_email)

        lay.addWidget(QLabel("Senha:"))
        self.inp_password = QLineEdit()
        self.inp_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.inp_password.setPlaceholderText("••••••••••••")
        lay.addWidget(self.inp_password)

        lay.addWidget(QLabel("Código de 2 Fatores / 2FA (deixe em branco se não usar):"))
        self.inp_tfa = QLineEdit()
        self.inp_tfa.setPlaceholderText("Ex: 123456 (opcional)")
        lay.addWidget(self.inp_tfa)

        self.lbl_feedback = QLabel("")
        self.lbl_feedback.setWordWrap(True)
        self.lbl_feedback.setProperty("class", "muted")
        lay.addWidget(self.lbl_feedback)

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Fechar")
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_cancel)
        btns.addStretch()

        self.btn_submit = QPushButton("🚀  Entrar e Ativar Host")
        self.btn_submit.setProperty("class", "primary")
        self.btn_submit.clicked.connect(self.do_login)
        btns.addWidget(self.btn_submit)
        lay.addLayout(btns)

    def _kessel_call(self, method, path, body=None, token=None):
        url = "https://kessel-api.parsec.app" + path
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as err:
            raw = err.read()
            try:
                parsed = json.loads(raw) if raw else {}
            except Exception:
                parsed = {"error": raw.decode(errors="replace")[:200]}
            return err.code, parsed

    def do_login(self):
        email = self.inp_email.text().strip()
        password = self.inp_password.text()
        tfa = self.inp_tfa.text().strip()
        if not email or not password:
            self.lbl_feedback.setStyleSheet("color: #f87171;")
            self.lbl_feedback.setText("Por favor, preencha o e-mail e a senha.")
            return

        self.btn_submit.setEnabled(False)
        self.lbl_feedback.setStyleSheet("color: #949bb0;")
        self.lbl_feedback.setText("Autenticando com kessel-api.parsec.app...")
        QApplication.processEvents()

        body = {
            "email": email,
            "password": password,
            "session_scopes": ["ws.host", "ws.client", "api.writer"],
        }
        if tfa:
            body["tfa"] = tfa

        try:
            status, answer = self._kessel_call("POST", "/v2/auth", body)
        except Exception as exc:
            self.btn_submit.setEnabled(True)
            self.lbl_feedback.setStyleSheet("color: #f87171;")
            self.lbl_feedback.setText(f"Erro de conexão: {exc}")
            return

        self.btn_submit.setEnabled(True)
        if status in (200, 201) and isinstance(answer, dict) and answer.get("session_id"):
            token = answer["session_id"]
            st_me, me_data = self._kessel_call("GET", "/me", token=token)
            acct_name = ""
            if st_me == 200 and isinstance(me_data, dict):
                acct_name = me_data.get("data", {}).get("name", "")
            uid = os.getuid()
            pulse_line = f"PULSE_SERVER=unix:/run/user/{uid}/pulse/native"
            script = (
                "mkdir -p /etc/lowlat && touch /etc/lowlat/lowlatd.env && chmod 640 /etc/lowlat/lowlatd.env && "
                f"(grep -q '^KESSEL_SESSION=' /etc/lowlat/lowlatd.env && sed -i 's|^KESSEL_SESSION=.*|KESSEL_SESSION={token}|' /etc/lowlat/lowlatd.env || echo 'KESSEL_SESSION={token}' >> /etc/lowlat/lowlatd.env) && "
                f"(grep -q '^PULSE_SERVER=' /etc/lowlat/lowlatd.env && sed -i 's|^PULSE_SERVER=.*|{pulse_line}|' /etc/lowlat/lowlatd.env || echo '{pulse_line}' >> /etc/lowlat/lowlatd.env) && "
                "systemctl restart lowlatd.service"
            )
            subprocess.Popen(["pkexec", "/bin/sh", "-c", script])
            QMessageBox.information(
                self,
                "Login concluído!",
                f"Autenticado com sucesso como '{acct_name or email}'!\n"
                "Confirme a janela de senha do sistema (Polkit) para gravar a sessão e reiniciar o Host.",
            )
            self.accept()
            return

        err_text = answer.get("error", "Falha na autenticação") if isinstance(answer, dict) else "Erro desconhecido"
        if status == 403 and "ip" in str(answer).lower():
            self.lbl_feedback.setStyleSheet("color: #fbbf24;")
            self.lbl_feedback.setText(
                "📩 O Parsec enviou um e-mail para confirmar este endereço IP.\n"
                "Clique no link de aprovação que chegou no seu e-mail (ou digite o código 2FA) e clique em Entrar novamente!"
            )
        else:
            self.lbl_feedback.setStyleSheet("color: #f87171;")
            self.lbl_feedback.setText(f"Recusado pelo Parsec (HTTP {status}): {err_text}")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Parsec Linux Host")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
