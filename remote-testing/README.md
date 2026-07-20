# Siri Remote 3rd gen (A2540) — testing

Base setup to inspect what each button on the Siri Remote sends, before
mapping it in Kodi.

## Which script do I run?

You develop on Windows but the target is a Raspberry Pi (Linux). Two paths:

| | Option A — on Windows | Option B — on the Pi |
|---|---|---|
| Script | `remote_test_windows.py` | `remote_test.py` |
| Library | `hidapi` (cross-platform) | `evdev` (Linux only) |
| Reads | raw HID report bytes | evdev keycodes (`KEY_UP`, …) |
| Good for | fast dev loop, no Pi needed | **source of truth** for the Kodi keymap |

Do **A** now to see the remote respond while you build. Do **B** once the Pi
is flashed — those keycodes are what actually go into the keymap. The byte
reports from A are close but not identical to B's keycodes, so don't hardcode
the Kodi mapping from A alone.

---

## Option A — test on Windows (raw HID)

1. Pair the remote: **Settings > Bluetooth & devices > Add device**. Put the
   remote in pairing mode by holding **Back + Volume Up ~5s**. It appears as a
   keyboard/HID device.
2. `pip install hidapi`
3. List HID devices and find the Apple one:
   ```powershell
   python remote_test_windows.py
   ```
4. Watch button reports (auto-picks the Apple device):
   ```powershell
   python remote_test_windows.py --watch
   ```
   Output looks like `REPORT (8 bytes): 01 00 00 51 00 00 00 00` — press each
   button and note which byte changes.

Caveat: Windows claims volume / play-pause as system media keys, so those may
not reach the script. The d-pad clicks, select, and back are the ones that
should come through — and those are what matter for Kodi navigation anyway.

---

## Option B — test on the Pi (evdev, the real thing)

From Windows you can push and run the Linux script in one step:

```powershell
.\run_on_pi.ps1 -PiHost pi@raspberrypi.local
```

This scp's `remote_test.py` to the Pi, installs `python3-evdev`, and runs it
over SSH. (Requires SSH enabled on the Pi.) Or do it manually on the Pi:

### 1. Pair the remote

With the ASUS USB-BT500 dongle plugged in:

```bash
sudo apt install bluez python3-evdev   # bluez is usually preinstalled
bluetoothctl
```

Inside `bluetoothctl`:

```
power on
agent on
default-agent
scan on
```

Now put the remote in pairing mode: **hold Back + Volume Up for ~5 seconds**
(hold it close to the dongle). A device named something like `Siri Remote`
should appear with its MAC address. Then:

```
pair XX:XX:XX:XX:XX:XX
trust XX:XX:XX:XX:XX:XX      # auto-reconnect after reboot
connect XX:XX:XX:XX:XX:XX
scan off
exit
```

`trust` is important — without it the remote won't reconnect on its own.

### 2. Run the tester

```bash
sudo python3 remote_test.py
```

(`sudo` is needed to read `/dev/input`; alternatively add your user to the
`input` group: `sudo usermod -aG input $USER` and re-login.)

It auto-detects the remote by name, prints its capabilities, then dumps every
event as you press buttons:

```
[/dev/input/event3] KEY KEY_VOLUMEUP (code 115) PRESSED
[/dev/input/event3] KEY KEY_VOLUMEUP (code 115) RELEASED
```

If auto-detection fails, run `sudo python3 remote_test.py --list` to see all
input devices and pass the right one explicitly:
`sudo python3 remote_test.py /dev/input/event3`

### 3. What to expect

Buttons that should produce events (exact keycodes to be confirmed with this
tester — that's the point):

| Button | Likely keycode |
|---|---|
| Clickpad ring up/down/left/right | KEY_UP / KEY_DOWN / KEY_LEFT / KEY_RIGHT |
| Clickpad center (select) | KEY_SELECT or KEY_ENTER |
| Back (<) | KEY_ESC or KEY_BACK |
| Play/Pause | KEY_PLAYPAUSE |
| Volume up/down | KEY_VOLUMEUP / KEY_VOLUMEDOWN |
| Mute | KEY_MUTE |
| Power / TV | KEY_POWER (may not arrive) |
| Siri button | usually nothing on Linux |

Known limitations (from plan.md): the touch surface swipes and gyroscope are
not supported on Linux — only physical clicks map.

Write down the actual keycodes printed; they go straight into the Kodi keymap
(`~/.kodi/userdata/keymaps/remote.xml`) in the next setup step.
