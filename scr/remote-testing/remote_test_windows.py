#!/usr/bin/env python3
"""Siri Remote (3rd gen, A2540) raw-HID tester for Windows.

The Linux script (remote_test.py) uses evdev, which doesn't exist on Windows.
This version reads raw HID reports via hidapi, so you can pair the remote to
your PC over Bluetooth and see what each button sends *while developing on
Windows* — before the Raspberry Pi is even set up.

What this tells you: the raw report bytes per button. This is close to, but
not identical to, the Linux evdev keycodes. Treat it as a fast dev-loop; the
authoritative keycodes for the Kodi keymap come from running remote_test.py
on the Pi (see README.md, "Option B").

Setup:
    1. Pair the Siri Remote to Windows: Settings > Bluetooth & devices >
       Add device. Put the remote in pairing mode by holding Back + Volume Up
       for ~5s. It shows up as a keyboard/HID device.
    2. pip install hidapi
    3. python remote_test_windows.py            # list HID devices
       python remote_test_windows.py --watch    # auto-pick + dump reports
       python remote_test_windows.py --vid 0x05ac --pid 0x0266   # explicit

Note: Windows may claim some buttons (volume/play-pause become system media
keys) before your script sees them. Buttons the OS ignores (d-pad clicks,
select, back) are the interesting ones and should come through as HID reports.
"""

import argparse
import sys
import time

try:
    import hid
except ImportError:
    sys.exit("Missing dependency. Run:  pip install hidapi")

# Apple's USB/BT vendor id. Siri Remote product ids vary by revision, so we
# match on vendor and let you confirm the exact device from the printed list.
APPLE_VID = 0x05AC


def list_devices():
    devices = hid.enumerate()
    if not devices:
        print("No HID devices found.")
        return []
    print(f"{'VID':<8} {'PID':<8} {'Manufacturer':<20} Product")
    for d in devices:
        vid = f"0x{d['vendor_id']:04x}"
        pid = f"0x{d['product_id']:04x}"
        man = (d.get("manufacturer_string") or "").strip()
        prod = (d.get("product_string") or "").strip()
        flag = "  <-- Apple" if d["vendor_id"] == APPLE_VID else ""
        print(f"{vid:<8} {pid:<8} {man:<20} {prod}{flag}")
    return devices


def pick_apple_device():
    for d in hid.enumerate():
        if d["vendor_id"] == APPLE_VID:
            return d["vendor_id"], d["product_id"]
    return None


def watch(vid, pid):
    dev = hid.device()
    try:
        dev.open(vid, pid)
    except OSError as e:
        sys.exit(f"Could not open device 0x{vid:04x}:0x{pid:04x} — {e}\n"
                 "It may be claimed exclusively by Windows, or not connected.")

    dev.set_nonblocking(True)
    print(f"Opened {dev.get_manufacturer_string()} "
          f"{dev.get_product_string()} (0x{vid:04x}:0x{pid:04x})")
    print("Press buttons on the remote (Ctrl+C to quit)\n")

    last = None
    try:
        while True:
            report = dev.read(64)
            if report:
                hex_bytes = " ".join(f"{b:02x}" for b in report)
                # Skip duplicate consecutive reports (held buttons repeat)
                if report != last:
                    print(f"REPORT ({len(report)} bytes): {hex_bytes}")
                    last = report
            else:
                time.sleep(0.005)
    except KeyboardInterrupt:
        print("\nDone.")
    finally:
        dev.close()


def main():
    parser = argparse.ArgumentParser(description="Siri Remote HID tester (Windows)")
    parser.add_argument("--watch", action="store_true",
                        help="open the remote and dump raw reports")
    parser.add_argument("--vid", type=lambda x: int(x, 0),
                        help="explicit vendor id, e.g. 0x05ac")
    parser.add_argument("--pid", type=lambda x: int(x, 0),
                        help="explicit product id, e.g. 0x0266")
    args = parser.parse_args()

    if not args.watch and args.vid is None:
        list_devices()
        return

    if args.vid is not None and args.pid is not None:
        watch(args.vid, args.pid)
        return

    picked = pick_apple_device()
    if not picked:
        print("No Apple HID device found. Is the remote paired and connected?\n")
        list_devices()
        sys.exit(1)
    watch(*picked)


if __name__ == "__main__":
    main()
