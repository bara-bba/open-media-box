# Open Media Box — Project Plan

## Goal

Repurpose an existing Raspberry Pi 3 as an open-source media box that streams Jellyfin from a local server, outputs 1080p via HDMI, and is controlled with a Siri Remote (3rd gen).

---

## Core Requirements

| Requirement | Detail |
|---|---|
| Jellyfin client | Stream from self-hosted Jellyfin server on local network |
| HDMI output | 1080p |
| Siri Remote 3rd gen (A2540) | Bluetooth, pairs as HID device on Linux |
| YouTube | Via Kodi add-on |
| Spotify | Via Spotify Connect (librespot / Raspotify) |
| AirPlay | Via UxPlay (background service) |
| Open source | All software stack must be open/free |

---

## Hardware

**Reusing existing Raspberry Pi 3** — built-in WiFi and Bluetooth are broken, replaced with USB dongles.

| Item                         | Link                                                                                                     | Notes                                                              |
| ---------------------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| Raspberry Pi 3               | already owned                                                                                            | WiFi + BT broken — replaced via USB                                |
| BrosTrend AX900 WiFi 6 USB   | [amazon.it](https://www.amazon.it/BrosTrend-AX900-WiFi-Linux-USB/dp/B0F6N1H84N)                          | explicitly Pi OS + Debian compatible, dual band                    |
| ASUS USB-BT500 Bluetooth 5.0 | [amazon.it](https://www.amazon.it/ASUS-Adattatore-Retrocompatibile-Generazioni-Tecnologia/dp/B08B9WQFTL) | RTL8761BU chip, in-kernel Linux driver, confirmed working on Pi OS |
| Noctua NF-A4x10 5V (3-pin)   | [amazon.it](https://www.amazon.it/Noctua-NF-A4x10-5V-PWM-silenziosa/dp/B07DXS86G7)                       | silent, **non-PWM** — full speed off 5V+GND; incl. Low-Noise Adapter to slow it |
| M2.5 brass PCB standoffs     | [amazon.it](https://www.amazon.it/Assortito-Distanziatori-Esagonali-Maschio-Distanziatore/dp/B0G4G7WQRM) | assorted kit, includes screws and nuts                             |
| Siri Remote 3rd gen (A2540)  | [Vinted](https://www.vinted.it)                                                                          | ~€40 used                                                          |
| MicroSD 32GB A2              | already owned                                                                                            | —                                                                  |
| Micro-USB PSU 5V 2.5A        | already owned                                                                                            | —                                                                  |

**Estimated purchase total: ~€58** (WiFi dongle + BT dongle + fan + Siri Remote ~€40 from Vinted — verify current prices)

---

## Software Stack

| Layer          | Choice                        | Notes                                                  |
| -------------- | ----------------------------- | ------------------------------------------------------ |
| OS             | **Raspberry Pi OS Lite**      | more flexible than LibreELEC for background services   |
| Media frontend | **Kodi**                      | Jellyfin add-on, YouTube add-on, full skin support     |
| Jellyfin       | Kodi add-on                   | library browsing, playback, resume, watched sync       |
| YouTube        | Kodi add-on                   | native                                                 |
| Spotify        | **Raspotify** (librespot)     | background service, shows up as Spotify Connect device |
| AirPlay        | **shairport-sync**            | audio-only receiver, background service — video mirroring **not** possible (Kodi holds the single display as DRM master) |
| Remote         | Siri Remote (A2854) via BT USB dongle | **a2854-siri-remote-linux** bridge — reads BLE button notifications via `btmon` (BlueZ HoG can't expose them), then maps to Kodi |

### Why Raspberry Pi OS over LibreELEC
LibreELEC is locked down — installing Raspotify and shairport-sync as background services requires SSH hacks. Raspberry Pi OS Lite + Kodi gives identical media experience with full Linux flexibility underneath.

> **Note on AirPlay:** original plan was UxPlay for full screen mirroring, but UxPlay needs to own the display and Kodi already holds it as DRM master (single-display GBM). Switched to **shairport-sync** for always-on AirPlay **audio** alongside Kodi. Video mirroring would require stopping Kodi.

---
## 3D Case

Custom case to be designed from scratch in CAD. Material: **PETG** (better heat resistance than PLA, good for enclosed electronics).

### Board confirmed
**Raspberry Pi 3 Model B v1.2** — use 3B STEP file, not 3B+.

### STEP reference model — board
- **Pi 3B**: [GrabCAD — Raspberry Pi 3 Model B](https://grabcad.com/library/raspberry-pi-3-model-b-reference-design-solidworks-cad-raspberry-pi-raspberrypi-rpi-1)

### Reference cases with 40mm fan (good starting point for custom model)
- [Pi 3 B/B+ case w/ 40mm fan — Printables](https://www.printables.com/model/242166-raspberry-pi-3-bb-case-w-40mm-fan) — fits both variants, accurate port cutouts
- [Pi 3B/+ case with fan — Printables](https://www.printables.com/model/72991-raspberry-pi-3b-case-with-fan) — alternative design

### Case requirements
- Noctua NF-A4x10 40mm fan mount (5V, 3-pin)
- HDMI, USB, microSD, and micro-USB port cutouts
- Ventilation slots
- Clean HTPC-style horizontal form factor

---

## Buying Tasks

- [x] Order WiFi dongle — **BrosTrend AX900** (first choice): [amazon.it](https://www.amazon.it/BrosTrend-AX900-WiFi-Linux-USB/dp/B0F6N1H84N) · fallback: **ALFA AWUS036ACS** (AC600, MT7610U, plug-and-play on Pi OS): [amazon.it](https://www.amazon.it/s?k=ALFA+AWUS036ACS) · ~~RT5370N (N/A)~~ ✅ 2026-07-18
- [x] Order Bluetooth dongle — [amazon.it](https://www.amazon.it/Bluetooth-Adattatore-Raspberry-auricolare-compatibile/dp/B07RNJ5QJS) ✅ 2026-07-18
- [x] Order 40mm fan — ordered GeeekPi ([amazon.it](https://www.amazon.it/GeeekPi-Raspberry-regolabile-raffreddamento-silenzioso/dp/B092ZF995F)) but **used Noctua NF-A4x10 5V (3-pin, non-PWM)** in the end ✅ 2026-07-18
- [x] Find Siri Remote 3rd gen on Vinted (~€40) — [vinted.it](https://www.vinted.it)
- [x] ~~PCB standoffs~~ — ordered ([amazon.it](https://www.amazon.it/Assortito-Distanziatori-Esagonali-Maschio-Distanziatore/dp/B0G4G7WQRM))
- [ ] Buy PETG filament for case printing

---

## 3D Modelling Tasks

- [x] Confirm board revision (3B or 3B+) -> 3B
- [x] Download correct STEP file from GrabCAD (links above) 
- [x] Model case body with fan mount and port cutouts ✅ 2026-07-18
- [ ] Print test fit in PLA first, then final in PETG

---

## Setup Tasks

- [x] Flash Raspberry Pi OS Lite to MicroSD ✅ 2026-07-18
- [x] Connect WiFi dongle and configure network (headless setup via `wpa_supplicant`) ✅ 2026-07-18
- [x] Install Kodi ✅ 2026-07-18
- [x] Install Jellyfin for Kodi add-on + log in ✅ 2026-07-19 — installed, logged in, libraries synced. Playback fixes: **`syncDuringPlay=false`** (sync-during-play crashed video), `maxBitrate` cap 20Mbps → server transcodes heavy files, proxy cuts large streams (point at `192.168.1.68:8096` direct on Pi 5)
- [x] Install YouTube Kodi add-on ✅ 2026-07-18 — installed; **one-time sign-in pending** at `google.com/device`
- [x] Install and configure Raspotify (Spotify Connect) ✅ 2026-07-18 — device name "open-media", HDMI out
- [x] Install and configure shairport-sync (AirPlay **audio** receiver — UxPlay dropped, see note above) ✅ 2026-07-18 — advertises as "open-media"
- [x] Pair Siri Remote via a2854-siri-remote-linux (`a2854_pair.py`) over BT USB dongle ✅ 2026-07-19 — paired (public addr `E0:C3:EA:…`); `bt-fix.service` brings the dongle up at boot (rfkill unblock + btusb reload). Pairing script patched (accept public addr, auto-confirm passkey, skip `sudo -v`)
- [x] Run a2854 bridge and map Siri Remote buttons to Kodi ✅ 2026-07-19 — `kodi-siri-bridge.service`; buttons on GATT handle `0x0039`; **context-aware** (menu navigate vs. video seek/OSD), hold-repeat, remote-battery indicator in the skin
- [x] Connect Noctua NF-A4x10 5V (3-pin) fan ✅ 2026-07-19 — **Red → 5V (pin 4), Black → GND (pin 6)**, yellow (tacho) unused. Runs full speed
- [x] Set Kodi to autostart on boot ✅ 2026-07-18 — `kodi.service` (GBM/DRM 1080p60, `getty@tty1` disabled)
- [x] (Optional) Enable SSH for remote management ✅ 2026-07-18 — key-based login
- [x] (Optional) Enable HDMI-CEC so TV remote also controls Kodi ✅ 2026-07-18 — `cec0` detected, works

---

## Known Limitations

- Siri Remote touchpad and gyroscope won't work on Linux — only d-pad, click, play/pause, back, and volume buttons map
- AirPlay is **audio-only** (shairport-sync) — no screen mirroring, because Kodi holds the single display as DRM master (UxPlay would need to own the screen)
- Pi 3 is less powerful than Pi 4 — 1080p playback is fine, avoid 4K or heavy skins
Ciaone
