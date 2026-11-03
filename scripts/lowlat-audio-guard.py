#!/usr/bin/env python3
"""Automatic PipeWire Audio Router for Parsec Linux Host (lowlat).

Automatically unlinks full hardware monitor sinks and voice chat apps
(Discord / WEBRTC VoiceEngine / Vesktop / etc.) from lowlat's audio capture,
and links all other application playback streams directly to lowlat:input_FL/FR.
"""

import json
import os
import subprocess
import time
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "lowlat" / "audio-guard.json"

DEFAULT_BLOCKED = [
    "webrtc voiceengine",
    "discord",
    "vesktop",
    "equibop",
    "teamspeak",
    "mumble",
]

SYSTEM_PREFIXES = (
    "alsa_output.",
    "alsa_input.",
    "bluez_output.",
    "bluez_input.",
    "midi-bridge",
    "bluez_midi",
    "lowlat",
)


def load_config() -> dict:
    cfg = {
        "enabled": True,
        "blocked": list(DEFAULT_BLOCKED),
    }
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text())
            if isinstance(data, dict):
                cfg["enabled"] = bool(data.get("enabled", True))
                if isinstance(data.get("blocked"), list):
                    cfg["blocked"] = [str(x).strip().lower() for x in data["blocked"] if str(x).strip()]
    except Exception:
        pass
    return cfg


def save_config(cfg: dict) -> None:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    except Exception:
        pass


def parse_pw_graph():
    """Return (outputs, inputs, links) from pw-link."""
    outputs = {}  # port_id -> (node_name, port_name)
    inputs = {}   # port_id -> (node_name, port_name)
    links = set() # (out_port_id, in_port_id)

    try:
        res_o = subprocess.run(["pw-link", "-Io"], capture_output=True, text=True, timeout=2)
        for line in res_o.stdout.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0].isdigit():
                pid = int(parts[0])
                node, port = parts[1].rsplit(":", 1)
                outputs[pid] = (node, port)

        res_i = subprocess.run(["pw-link", "-Ii"], capture_output=True, text=True, timeout=2)
        for line in res_i.stdout.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0].isdigit():
                pid = int(parts[0])
                node, port = parts[1].rsplit(":", 1)
                inputs[pid] = (node, port)

        res_l = subprocess.run(["pw-link", "-Il"], capture_output=True, text=True, timeout=2)
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
    except Exception:
        pass

    return outputs, inputs, links


def is_blocked_node(node_name: str, blocked_patterns: list[str]) -> bool:
    low = node_name.lower()
    for pat in blocked_patterns:
        if pat and pat in low:
            return True
    return False


def is_system_node(node_name: str) -> bool:
    low = node_name.lower()
    return low.startswith(SYSTEM_PREFIXES)


def enforce_once(cfg: dict | None = None) -> dict:
    """Enforce PipeWire routing rules once and return current status summary."""
    if cfg is None:
        cfg = load_config()

    outputs, inputs, links = parse_pw_graph()

    lowlat_fl = None
    lowlat_fr = None
    for pid, (node, port) in inputs.items():
        if node == "lowlat":
            if port == "input_FL":
                lowlat_fl = pid
            elif port == "input_FR":
                lowlat_fr = pid

    apps = {}  # node_name -> {"blocked": bool, "linked": bool}
    for pid, (node, port) in outputs.items():
        if is_system_node(node) or not port.startswith("output_"):
            continue
        blocked = is_blocked_node(node, cfg["blocked"])
        is_linked = (
            (lowlat_fl is not None and (pid, lowlat_fl) in links)
            or (lowlat_fr is not None and (pid, lowlat_fr) in links)
        )
        prev = apps.get(node, {"blocked": blocked, "linked": False})
        apps[node] = {"blocked": blocked, "linked": prev["linked"] or is_linked}

    if lowlat_fl is None or lowlat_fr is None:
        return {"streaming_audio": False, "apps": apps}

    if not cfg.get("enabled", True):
        # Restore standard monitor capture and unlink direct app links
        for out_pid, in_pid in list(links):
            if in_pid not in (lowlat_fl, lowlat_fr):
                continue
            out_info = outputs.get(out_pid)
            if out_info and not out_info[1].startswith("monitor_"):
                subprocess.run(["pw-link", "-d", str(out_pid), str(in_pid)], capture_output=True, timeout=1)
        for out_pid, (node, port) in outputs.items():
            if node.startswith("alsa_output.pci"):
                if port == "monitor_FL" and (out_pid, lowlat_fl) not in links:
                    subprocess.run(["pw-link", str(out_pid), str(lowlat_fl)], capture_output=True, timeout=1)
                elif port == "monitor_FR" and (out_pid, lowlat_fr) not in links:
                    subprocess.run(["pw-link", str(out_pid), str(lowlat_fr)], capture_output=True, timeout=1)
        return {"streaming_audio": True, "apps": apps}

    # 1. Unlink any hardware monitor or blocked app from lowlat:input_FL / input_FR
    for out_pid, in_pid in list(links):
        if in_pid not in (lowlat_fl, lowlat_fr):
            continue
        out_info = outputs.get(out_pid)
        if not out_info:
            continue
        node, port = out_info
        if port.startswith("monitor_") or is_system_node(node) or is_blocked_node(node, cfg["blocked"]):
            subprocess.run(
                ["pw-link", "-d", str(out_pid), str(in_pid)],
                capture_output=True,
                timeout=1,
            )

    # 2. Link all allowed application output_FL / output_FR / output_MONO ports to lowlat
    for out_pid, (node, port) in outputs.items():
        if is_system_node(node) or is_blocked_node(node, cfg["blocked"]):
            continue
        if port == "output_FL" and (out_pid, lowlat_fl) not in links:
            subprocess.run(
                ["pw-link", str(out_pid), str(lowlat_fl)],
                capture_output=True,
                timeout=1,
            )
            if node in apps:
                apps[node]["linked"] = True
        elif port == "output_FR" and (out_pid, lowlat_fr) not in links:
            subprocess.run(
                ["pw-link", str(out_pid), str(lowlat_fr)],
                capture_output=True,
                timeout=1,
            )
            if node in apps:
                apps[node]["linked"] = True
        elif port == "output_MONO":
            if (out_pid, lowlat_fl) not in links:
                subprocess.run(["pw-link", str(out_pid), str(lowlat_fl)], capture_output=True, timeout=1)
            if (out_pid, lowlat_fr) not in links:
                subprocess.run(["pw-link", str(out_pid), str(lowlat_fr)], capture_output=True, timeout=1)
            if node in apps:
                apps[node]["linked"] = True

    return {"streaming_audio": True, "apps": apps}


def main():
    if not CONFIG_PATH.exists():
        save_config(load_config())
    while True:
        try:
            enforce_once()
        except Exception:
            pass
        time.sleep(0.8)


if __name__ == "__main__":
    main()
