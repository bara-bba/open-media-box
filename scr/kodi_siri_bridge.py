#!/usr/bin/env python3
"""
Siri Remote (A2854) -> Kodi bridge.

Reads BLE ATT notifications from `btmon` (button clicks arrive on GATT handle
0x0039 as a 2-byte code; 0x0000 = release) and drives Kodi.

Context-aware: in menus/OSD the d-pad navigates; during fullscreen video the
d-pad seeks and the centre click opens the OSD (Kodi's navigation methods don't
seek in video, so playback needs the named actions). Volume/d-pad auto-repeat
while held. Power toggles the TV via HDMI-CEC. Reports remote battery to a Home
window property (+ low-battery popup). Touchpad motion (0x003d) and the Siri
voice button (0x0036) are ignored.

Run as root (btmon needs no sudo). Designed to run under systemd.
"""
import base64
import json
import os
import pty
import re
import select
import subprocess
import time
import urllib.request

BTN_HANDLE = "0x0039"

# --- menu / OSD navigation map -------------------------------------------------
NAV_BUTTONS = {
    0x0002: ("rpc", "Input.Up", {}),
    0x0008: ("rpc", "Input.Down", {}),
    0x0004: ("rpc", "Input.Right", {}),
    0x0010: ("rpc", "Input.Left", {}),
    0x0800: ("rpc", "Input.Select", {}),
    0x4000: ("rpc", "Input.Back", {}),
    0x0001: ("rpc", "Input.ExecuteAction", {"action": "playpause"}),
    0x0200: ("rpc", "Input.ExecuteAction", {"action": "volumeup"}),
    0x0400: ("rpc", "Input.ExecuteAction", {"action": "volumedown"}),
    0x8000: ("rpc", "Input.ExecuteAction", {"action": "mute"}),
    0x0100: ("rpc", "Input.Home", {}),                 # TV button -> Home
    0x1000: ("builtin", "CECToggleState()"),           # Power -> TV off/on via CEC
}

# --- fullscreen-video overrides (seek / OSD / stop) ---------------------------
VIDEO_BUTTONS = {
    0x0004: ("rpc", "Input.ExecuteAction", {"action": "stepforward"}),   # Right seek +
    0x0010: ("rpc", "Input.ExecuteAction", {"action": "stepback"}),      # Left  seek -
    0x0002: ("rpc", "Input.ExecuteAction", {"action": "bigstepforward"}),# Up  big seek +
    0x0008: ("rpc", "Input.ExecuteAction", {"action": "bigstepback"}),   # Down big seek -
    0x0800: ("rpc", "Input.ExecuteAction", {"action": "osd"}),           # centre -> OSD
    0x4000: ("rpc", "Input.ExecuteAction", {"action": "stop"}),          # Back -> stop
    # playpause / volume / mute / power inherit from NAV_BUTTONS
}

# auto-repeat while held (volume + d-pad seek/navigate)
REPEATABLE = {0x0200, 0x0400, 0x0002, 0x0008, 0x0004, 0x0010}
INITIAL_DELAY = 0.35
REPEAT_INTERVAL = 0.12

# window ids for context detection
WIN_FULLSCREEN_VIDEO = 12005
WIN_FULLSCREEN_OSD = 12901

# Remote MAC + Kodi web creds come from the environment (see .env / the
# systemd unit's Environment= lines); the defaults are safe placeholders.
REMOTE_MAC = os.environ.get("REMOTE_MAC", "AA:BB:CC:DD:EE:FF")
BATTERY_DEV = "/org/bluez/hci0/dev_" + REMOTE_MAC.replace(":", "_")
BATTERY_INTERVAL = 120
BATTERY_LOW = 20
MODE_INTERVAL = 1.0     # how often to re-check what's on screen

KODI_URL = "http://localhost:8080/jsonrpc"
KODI_AUTH = base64.b64encode(
    f"{os.environ.get('KODI_WEB_USER', 'kodi')}:"
    f"{os.environ.get('KODI_WEB_PASS', 'kodi')}".encode()).decode()

HANDLE_RE = re.compile(r"Handle: (0x[0-9a-f]{4})")
DATA_RE = re.compile(r"Data\[\d+\]: ([0-9a-f]+)")


def kodi_rpc(method, params, want_result=False):
    body = json.dumps({"jsonrpc": "2.0", "id": 1,
                       "method": method, "params": params}).encode()
    req = urllib.request.Request(
        KODI_URL, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Basic " + KODI_AUTH})
    try:
        resp = urllib.request.urlopen(req, timeout=2).read()
        if want_result:
            return json.loads(resp).get("result")
    except Exception as exc:                       # noqa: BLE001
        if want_result:
            return None
        print("kodi rpc error:", exc, flush=True)
    return None


def kodi_builtin(func):
    try:
        subprocess.run(["kodi-send", "--action=" + func], timeout=3,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:                       # noqa: BLE001
        print("kodi builtin error:", exc, flush=True)


def dispatch(action):
    if action is None:
        return
    if action[0] == "rpc":
        kodi_rpc(action[1], action[2])
    elif action[0] == "builtin":
        kodi_builtin(action[1])


def resolve(code, mode):
    """Pick the action for a button given the on-screen context."""
    if mode == "video":
        a = VIDEO_BUTTONS.get(code)
        if a:
            return a
    return NAV_BUTTONS.get(code)


def get_mode():
    r = kodi_rpc("GUI.GetProperties", {"properties": ["currentwindow"]},
                 want_result=True)
    try:
        wid = r["currentwindow"]["id"]
    except (TypeError, KeyError):
        return None
    if wid == WIN_FULLSCREEN_VIDEO:
        return "video"
    if wid == WIN_FULLSCREEN_OSD:
        return "osd"
    return "gui"


def read_battery():
    try:
        out = subprocess.run(
            ["busctl", "get-property", "org.bluez", BATTERY_DEV,
             "org.bluez.Battery1", "Percentage"],
            capture_output=True, text=True, timeout=4).stdout.split()
        if len(out) == 2 and out[0] == "y":
            return int(out[1])
    except Exception:                              # noqa: BLE001
        pass
    return None


def update_battery(bstate):
    pct = read_battery()
    if pct is None:
        return
    kodi_builtin(f"SetProperty(SiriRemoteBattery,{pct}%,home)")
    kodi_builtin(f"SetProperty(SiriRemoteBatteryLevel,{pct},home)")
    if pct <= BATTERY_LOW and not bstate["warned"]:
        kodi_rpc("GUI.ShowNotification",
                 {"title": "Siri Remote", "message": f"Battery low: {pct}%",
                  "displaytime": 8000})
        bstate["warned"] = True
    elif pct > BATTERY_LOW + 5:
        bstate["warned"] = False


def handle_code(code, state, mode):
    if code == 0:                                  # release
        state["held"] = None
        state["held_action"] = None
        return
    action = resolve(code, mode)
    if code in REPEATABLE:
        if state["held"] != code:                  # new press -> fire once, arm repeat
            state["held"] = code
            state["held_action"] = action
            state["next_fire"] = time.monotonic() + INITIAL_DELAY
            dispatch(action)
            print(f"btn {code:#06x} [{mode}] -> {action} (hold-repeat)", flush=True)
        return
    state["held"] = None
    state["held_action"] = None
    if action:
        print(f"btn {code:#06x} [{mode}] -> {action}", flush=True)
        dispatch(action)
    else:
        print(f"btn {code:#06x} (unmapped)", flush=True)


def main():
    pid, fd = pty.fork()
    if pid == 0:                                   # child -> btmon on a PTY
        os.execvp("btmon", ["btmon"])
        os._exit(1)

    print("bridge up: reading btmon, driving Kodi", flush=True)
    buf = b""
    cur_handle = None
    state = {"held": None, "held_action": None, "next_fire": 0.0}
    bstate = {"warned": False}
    mstate = {"mode": "gui", "next": 0.0}
    last_batt = 0.0

    while True:
        now = time.monotonic()
        if now - last_batt >= BATTERY_INTERVAL:
            last_batt = now
            update_battery(bstate)
        if now >= mstate["next"]:
            mstate["next"] = now + MODE_INTERVAL
            m = get_mode()
            if m:
                mstate["mode"] = m

        if state["held"] is not None:
            timeout = max(0.0, state["next_fire"] - time.monotonic())
        else:
            timeout = min(1.0, max(0.05, mstate["next"] - time.monotonic()))
        r, _, _ = select.select([fd], [], [], timeout)

        # auto-repeat for held keys (uses the action resolved at press time)
        if state["held"] is not None and time.monotonic() >= state["next_fire"]:
            dispatch(state["held_action"])
            state["next_fire"] = time.monotonic() + REPEAT_INTERVAL

        if fd not in r:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            line = raw.decode(errors="ignore")
            m = HANDLE_RE.search(line)
            if m:
                cur_handle = m.group(1)
                continue
            d = DATA_RE.search(line)
            if d and cur_handle == BTN_HANDLE:
                cur_handle = None
                handle_code(int(d.group(1), 16), state, mstate["mode"])


if __name__ == "__main__":
    main()
