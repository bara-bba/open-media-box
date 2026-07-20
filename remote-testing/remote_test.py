#!/usr/bin/env python3
"""Siri Remote (3rd gen, A2540) event tester for Linux / Raspberry Pi OS.

The remote pairs over Bluetooth as a standard HID device, so its buttons
arrive as normal Linux input events. This script finds the remote's input
device(s) and prints every event with its keycode name, so you can discover
what each button sends before mapping it in Kodi.

Usage (run on the Pi, after pairing — see README.md):

    sudo python3 remote_test.py                  # auto-detect the remote
    sudo python3 remote_test.py --list           # list all input devices
    sudo python3 remote_test.py /dev/input/event5  # use a specific device

Requires: pip install evdev  (Linux only)
"""

import argparse
import selectors
import sys

from evdev import InputDevice, categorize, ecodes, list_devices

# Substrings used to auto-detect the remote among input devices
NAME_HINTS = ("siri", "apple")

# Key state values in EV_KEY events
KEY_STATES = {0: "RELEASED", 1: "PRESSED", 2: "HELD"}


def find_devices():
    """Return all input devices whose name looks like the Siri Remote."""
    devices = [InputDevice(path) for path in list_devices()]
    return [d for d in devices if any(h in d.name.lower() for h in NAME_HINTS)]


def print_all_devices():
    devices = [InputDevice(path) for path in list_devices()]
    if not devices:
        print("No input devices found. Are you running with sudo "
              "(or is your user in the 'input' group)?")
        return
    print(f"{'Path':<20} {'Name':<40} Phys")
    for d in devices:
        print(f"{d.path:<20} {d.name:<40} {d.phys}")


def print_capabilities(device):
    print(f"\n--- {device.path}: {device.name} ---")
    caps = device.capabilities(verbose=True)
    for (ev_name, _), codes in caps.items():
        if ev_name == "EV_SYN":
            continue
        names = ", ".join(str(code[0]) for code in codes)
        print(f"  {ev_name}: {names}")


def monitor(devices):
    selector = selectors.DefaultSelector()
    for d in devices:
        selector.register(d, selectors.EVENT_READ)

    print("\nListening for events — press buttons on the remote (Ctrl+C to quit)\n")
    while True:
        for key, _ in selector.select():
            device = key.fileobj
            for event in device.read():
                if event.type == ecodes.EV_KEY:
                    key_event = categorize(event)
                    state = KEY_STATES.get(event.value, event.value)
                    print(f"[{device.path}] KEY {key_event.keycode} "
                          f"(code {event.code}) {state}")
                elif event.type == ecodes.EV_ABS:
                    code_name = ecodes.ABS.get(event.code, event.code)
                    print(f"[{device.path}] ABS {code_name} = {event.value}")
                elif event.type == ecodes.EV_REL:
                    code_name = ecodes.REL.get(event.code, event.code)
                    print(f"[{device.path}] REL {code_name} = {event.value}")
                # EV_SYN and EV_MSC are noise for this purpose — skipped


def main():
    parser = argparse.ArgumentParser(description="Siri Remote event tester")
    parser.add_argument("device", nargs="?",
                        help="explicit /dev/input/eventN path")
    parser.add_argument("--list", action="store_true",
                        help="list all input devices and exit")
    args = parser.parse_args()

    if args.list:
        print_all_devices()
        return

    if args.device:
        devices = [InputDevice(args.device)]
    else:
        devices = find_devices()
        if not devices:
            print("No Siri/Apple remote found among input devices.\n"
                  "Is it paired and connected? (see README.md)\n"
                  "All devices currently visible:\n")
            print_all_devices()
            sys.exit(1)

    for d in devices:
        print_capabilities(d)

    try:
        monitor(devices)
    except KeyboardInterrupt:
        print("\nDone.")


if __name__ == "__main__":
    main()
