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
import glob
import json
import os
import pty
import re
import select
import subprocess
import time
import urllib.error
import urllib.parse
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
# systemd unit's Environment= lines). If REMOTE_MAC is unset or left at the
# placeholder, the first *paired* Bluetooth device is used (this box pairs
# only the Siri Remote).
def _detect_remote_mac():
    mac = os.environ.get("REMOTE_MAC", "")
    if mac and mac != "AA:BB:CC:DD:EE:FF":
        return mac
    try:
        out = subprocess.run(["bluetoothctl", "devices", "Paired"],
                             capture_output=True, text=True, timeout=8).stdout
        m = re.search(r"([0-9A-F]{2}(?::[0-9A-F]{2}){5})", out)
        if m:
            return m.group(1)
    except Exception:                              # noqa: BLE001
        pass
    return "AA:BB:CC:DD:EE:FF"


REMOTE_MAC = _detect_remote_mac()
def _find_device_path():
    """BlueZ object path for the remote. The adapter is not always hci0 — a
    USB dongle shows up as hci1 — so look the device up instead of guessing.
    """
    node = "dev_" + REMOTE_MAC.replace(":", "_")
    try:
        for path in sorted(glob.glob(f"/sys/class/bluetooth/hci*")):
            hci = os.path.basename(path)
            out = subprocess.run(
                ["busctl", "get-property", "org.bluez",
                 f"/org/bluez/{hci}/{node}", "org.bluez.Device1", "Address"],
                capture_output=True, text=True, timeout=4)
            if out.returncode == 0:
                return f"/org/bluez/{hci}/{node}"
    except Exception:                              # noqa: BLE001
        pass
    return f"/org/bluez/hci0/{node}"


BATTERY_DEV = _find_device_path()
BATTERY_INTERVAL = 120
BATTERY_LOW = 20
BATTERY_CRITICAL = 10
CHARGING_HOLD = 900                             # seconds a rising level counts as "charging"
CRITICAL_REPEAT = 1800                          # re-warn this often while critical
BATTERY_FILE = "/var/lib/kodi-siri-bridge/battery"   # last known level (survives restarts)
MODE_INTERVAL = 1.0     # how often to re-check what's on screen

# Reconnect watchdog: if the remote drops (out of range / sleep), BlueZ does
# not always chase it — actively retry the connection until it's back.
RECONNECT_INTERVAL = 15   # seconds between connection checks / attempts
BOND_SETTLE_SECS = 300    # don't re-arm within this long of bridge startup —
                          # cycling a just-created bond destroys it

KODI_URL = "http://localhost:8080/jsonrpc"
KODI_AUTH = base64.b64encode(
    f"{os.environ.get('KODI_WEB_USER', 'kodi')}:"
    f"{os.environ.get('KODI_WEB_PASS', 'kodi')}".encode()).decode()

_hdmi_device_cache = []   # memoises hdmi_alsa_device()

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


def kodi_player_active():
    """True if Kodi is *actively playing* (not merely paused).

    A paused Kodi keeps its player object but releases the ALSA device, so
    treating "paused" as active would hold the audio hostage and stop the
    music services from ever coming back.
    """
    players = kodi_rpc("Player.GetActivePlayers", {}, want_result=True)
    if not players:
        return False
    pid = players[0].get("playerid", 1)
    props = kodi_rpc("Player.GetProperties",
                     {"playerid": pid, "properties": ["speed"]},
                     want_result=True)
    if props is None:                              # can't tell -> assume busy
        return True
    return props.get("speed", 0) != 0


def hdmi_alsa_device():
    """ALSA device for the HDMI output, cached after the first lookup.

    Pi 3/4 expose a single card named "vc4hdmi"; the Pi 5 has one per
    micro-HDMI port ("vc4hdmi0"/"vc4hdmi1"), so the name can't be hardcoded.
    Prefer a card whose ELD reports an attached display.
    """
    if _hdmi_device_cache:
        return _hdmi_device_cache[0]
    card = None
    try:
        for eld in sorted(glob.glob("/proc/asound/card*/eld*")):
            try:
                text = open(eld).read()
            except OSError:
                continue
            name = ""
            for line in text.splitlines():
                if line.startswith("monitor_name"):
                    name = line.split(None, 1)[1].strip() if len(
                        line.split(None, 1)) > 1 else ""
            if not name:
                continue
            idx = re.search(r"/card(\d+)/", eld)
            if idx:
                link = f"/proc/asound/card{idx.group(1)}/id"
                try:
                    card = open(link).read().strip()
                    break
                except OSError:
                    pass
        if not card:                                # no display info: first vc4
            for idf in sorted(glob.glob("/proc/asound/card*/id")):
                cid = open(idf).read().strip()
                if cid.startswith("vc4hdmi"):
                    card = cid
                    break
    except Exception:                               # noqa: BLE001
        pass
    device = f"plughw:CARD={card or 'vc4hdmi'},DEV=0"
    _hdmi_device_cache.append(device)
    return device


AIRPLAY_SERVICE = "shairport-sync"


def kick_kodi_audio():
    """Force Kodi's AudioEngine to re-open its ALSA sink.

    Re-applying the audio device setting makes Kodi tear down and re-init the
    sink, which recovers it from a cached "no sink was returned" failure.
    """
    dev = kodi_rpc("Settings.GetSettingValue",
                   {"setting": "audiooutput.audiodevice"}, want_result=True)
    dev = (dev or {}).get("value")
    if not dev:
        return
    alt = ("ALSA:@" if dev != "ALSA:@" else "ALSA:default")
    kodi_rpc("Settings.SetSettingValue",
             {"setting": "audiooutput.audiodevice", "value": alt})
    time.sleep(0.6)
    kodi_rpc("Settings.SetSettingValue",
             {"setting": "audiooutput.audiodevice", "value": dev})


def wait_device_free(timeout=6.0):
    """Block until nothing holds the HDMI PCM, or `timeout` elapses.

    Pausing Spotify does not free the exclusive device instantly — librespot
    finishes its buffer first. Kicking Kodi's sink before that happens just
    reproduces the "device busy" failure it then caches, leaving the film
    silent. Returns True if the device came free.
    """
    m = re.search(r"CARD=([^,]+)", hdmi_alsa_device())
    path = f"/proc/asound/{m.group(1) if m else 'vc4hdmi'}/pcm0p/sub0/status"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if open(path).read().lstrip().startswith("closed"):
                return True
        except OSError:
            return True                            # can't tell — don't block
        time.sleep(0.25)
    return False


def enforce_kodi_priority(pstate):
    """Kodi owns the HDMI output while it plays.

    Spotify is handled by the in-Kodi addon now, so it shares Kodi's player
    and needs no arbitration. Only AirPlay still opens the exclusive ALSA
    device behind Kodi's back, so it is stopped for the duration of playback.
    """
    kodi = kodi_player_active()
    if kodi == pstate["kodi"]:
        return
    try:
        if kodi:
            print("kodi started — stopping AirPlay", flush=True)
            subprocess.run(["systemctl", "stop", AIRPLAY_SERVICE], timeout=20)
            if not wait_device_free():
                print("  warning: HDMI device still busy", flush=True)
            kick_kodi_audio()
        else:
            print("kodi idle — AirPlay available again", flush=True)
            subprocess.run(["systemctl", "start", AIRPLAY_SERVICE], timeout=20)
    except Exception as exc:                       # noqa: BLE001
        print("priority switch error:", exc, flush=True)
    pstate["kodi"] = kodi


def remote_connected():
    """True if the remote's BlueZ device object reports Connected."""
    try:
        out = subprocess.run(
            ["busctl", "get-property", "org.bluez", BATTERY_DEV,
             "org.bluez.Device1", "Connected"],
            capture_output=True, text=True, timeout=4).stdout.split()
        return len(out) == 2 and out[1] == "true"
    except Exception:                              # noqa: BLE001
        return False


def cycle_connection():
    """Force a clean disconnect/reconnect. After a range drop the bonded
    remote often reconnects by itself into a 'zombie' state — Connected: yes
    but its button notifications never resume. A forced cycle re-arms them."""
    print(f"re-arming {REMOTE_MAC} (disconnect/reconnect cycle)", flush=True)
    try:
        subprocess.run(["bluetoothctl", "disconnect", REMOTE_MAC],
                       capture_output=True, text=True, timeout=10)
    except Exception:                              # noqa: BLE001
        pass
    time.sleep(3)
    try:
        subprocess.run(["bluetoothctl", "connect", REMOTE_MAC],
                       capture_output=True, text=True, timeout=12)
    except Exception:                              # noqa: BLE001
        pass


def try_reconnect(rstate):
    """Watchdog: chase the remote when it drops, and re-arm the link after it
    comes back from a real absence (>= 2 polls, i.e. ~30s) — that's when the
    zombie state appears.

    The re-arm is deliberately conservative: a disconnect/reconnect cycle run
    against a *freshly created* bond destroys it (the remote keeps its keys,
    BlueZ loses its own, and every later pairing fails with auth 0x05 — the
    remote then has to be reset before it will bond again). So it never runs
    at startup, and never within BOND_SETTLE_SECS of the bridge coming up.
    """
    up = remote_connected()
    now = time.monotonic()
    if up:
        if not rstate["connected"]:
            print(f"remote {REMOTE_MAC} reconnected", flush=True)
            notify("Siri Remote", "Connected", "link.png")
            rstate["just_up"] = True
            settled = (now - rstate["started_at"]) >= BOND_SETTLE_SECS
            if rstate["need_rearm"] and settled:
                rstate["need_rearm"] = False
                cycle_connection()
            elif rstate["need_rearm"]:
                # too soon after startup — a cycle here risks the bond
                print("  (skipping re-arm: bond may still be settling)",
                      flush=True)
                rstate["need_rearm"] = False
        rstate["connected"] = True
        rstate["down_polls"] = 0
        return
    rstate["down_polls"] += 1
    if rstate["connected"]:
        print(f"remote {REMOTE_MAC} disconnected — will retry", flush=True)
        notify("Siri Remote", "Disconnected", "link-slash.png")
    rstate["connected"] = False
    if rstate["down_polls"] >= 2:      # real absence, not our own brief cycle
        rstate["need_rearm"] = True
    try:
        subprocess.run(["bluetoothctl", "connect", REMOTE_MAC],
                       capture_output=True, text=True, timeout=10)
    except Exception:                              # noqa: BLE001
        pass


SKIN_ICONS = "special://skin/extras/icons"


def notify(title, message, icon=None, seconds=4):
    """Kodi toast notification, optionally with a skin icon."""
    params = {"title": title, "message": message,
              "displaytime": int(seconds * 1000)}
    if icon:
        params["image"] = f"{SKIN_ICONS}/{icon}"
    kodi_rpc("GUI.ShowNotification", params)


def load_last_battery():
    try:
        with open(BATTERY_FILE) as f:
            return int(f.read().strip())
    except Exception:                              # noqa: BLE001
        return None


def save_last_battery(pct):
    try:
        os.makedirs(os.path.dirname(BATTERY_FILE), exist_ok=True)
        with open(BATTERY_FILE, "w") as f:
            f.write(str(pct))
    except OSError:
        pass


def update_battery(bstate):
    """Publish the level to the header (and warn). When the remote is asleep
    or Kodi just restarted, the last known level is shown instead of nothing."""
    fresh = read_battery()
    bstate["stale"] = fresh is None
    pct = fresh if fresh is not None else bstate.get("last")
    if pct is None:
        return
    if fresh is not None and fresh != bstate.get("last"):
        bstate["last"] = fresh
        save_last_battery(fresh)
    kodi_builtin(f"SetProperty(SiriRemoteBattery,{pct}%,home)")
    kodi_builtin(f"SetProperty(SiriRemoteBatteryLevel,{pct},home)")
    if fresh is None:
        return                                     # only warn on a live reading
    now = time.monotonic()
    # BlueZ exposes no charging flag, so infer it: a rising level means the
    # remote is on the charger -> no warnings until it has been falling a while.
    prev = bstate.get("prev")
    bstate["prev"] = fresh
    if prev is not None and fresh > prev:
        bstate["charging_until"] = now + CHARGING_HOLD
    if now < bstate.get("charging_until", 0):
        bstate["warned"] = False
        return
    if fresh <= BATTERY_CRITICAL:
        if now - bstate.get("critical_at", -CRITICAL_REPEAT) >= CRITICAL_REPEAT:
            bstate["critical_at"] = now
            notify("Siri Remote", f"Battery critical: {fresh}%",
                   "battery-empty.png", seconds=12)
        bstate["warned"] = True
    elif fresh <= BATTERY_LOW:
        if not bstate["warned"]:
            notify("Siri Remote", f"Battery low: {fresh}%",
                   "battery-quarter.png", seconds=8)
            bstate["warned"] = True
    elif fresh > BATTERY_LOW + 5:
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
    bstate = {"warned": False, "stale": False, "last": load_last_battery()}
    mstate = {"mode": "gui", "next": 0.0}
    # need_rearm starts False: never cycle the link at startup. Doing so on a
    # bond created moments earlier permanently breaks it (see try_reconnect).
    rstate = {"connected": False, "down_polls": 0, "need_rearm": False,
              "started_at": time.monotonic()}
    # Start from Kodi's real state, so a bridge restart mid-playback doesn't
    # leave the music services stopped forever (or evict them needlessly).
    pstate = {"kodi": kodi_player_active()}
    if not pstate["kodi"]:
        try:                                       # undo any stale stop
            subprocess.run(["systemctl", "start", AIRPLAY_SERVICE], timeout=20)
        except Exception:                          # noqa: BLE001
            pass
    last_batt = 0.0
    last_reconnect = 0.0

    while True:
        now = time.monotonic()
        if now - last_batt >= BATTERY_INTERVAL:
            last_batt = now
            update_battery(bstate)
            if bstate["stale"] and rstate["connected"]:
                last_batt = now - BATTERY_INTERVAL + 15   # link just came up: retry soon
        if now - last_reconnect >= RECONNECT_INTERVAL:
            last_reconnect = now
            try_reconnect(rstate)
            if rstate.pop("just_up", False):       # re-warn once per connection
                bstate["warned"] = False
                last_batt = 0.0
        if now >= mstate["next"]:
            mstate["next"] = now + MODE_INTERVAL
            m = get_mode()
            if m:
                mstate["mode"] = m
            enforce_kodi_priority(pstate)

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
