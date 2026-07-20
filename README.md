# Open Media Box — Setup & Operation

Raspberry Pi 3 running Kodi as an open-source media box: 1080p HDMI, streams
Jellyfin / YouTube / Spotify (Connect) / AirPlay audio, controlled by an Apple
Siri Remote, the TV remote (HDMI-CEC), or a phone.

This documents what was actually built. Design rationale + task list: [[plan]].
Rebuild-on-a-new-Pi script: [`provision-pi5.sh`](scr/provision-pi5.sh) (+ [`kodi_siri_bridge.py`](scr/kodi_siri_bridge.py)).

> **Config:** values shown as `<PLACEHOLDER>` (IPs, hostname, Wi-Fi SSID, Kodi
> password, remote MAC) are your own — copy [`.env.example`](.env.example) to
> `.env` (gitignored) and fill them in. The scripts read them from there.

---

## Hardware

| Part | Detail |
|---|---|
| Board | Raspberry Pi 3 Model B v1.2 (1 GB) |
| Wi-Fi | BrosTrend AX900 USB (Realtek **RTL8821AU** — works in-kernel on 6.18) |
| Bluetooth | ASUS USB-BT500 (Realtek **RTL8761BU**) — onboard Pi BT is broken, disabled |
| Storage / PSU | 32 GB microSD A2, 5 V 2.5 A micro-USB |
| Cooling | Noctua NF-A4x10 5V (3-pin, non-PWM) 40 mm fan — Red→5V (pin 4), Black→GND (pin 6), yellow unused |
| Power button | Arcade (momentary) switch — **GPIO3 (pin 5) + GND (pin 9)** |
| Output | HDMI 1080p60 to TV |

### Power button
An arcade momentary button on **GPIO3 (pin 5)** and any **GND** (pin 9) acts as
the power button once `dtoverlay=gpio-shutdown` is set in
`/boot/firmware/config.txt`:
- **Press while off (halted)** → boots the Pi (GPIO3 is the only wake-from-halt pin)
- **Press while running** → clean shutdown

```bash
# enable the button (needs sudo), then reboot once
echo 'dtoverlay=gpio-shutdown' | sudo tee -a /boot/firmware/config.txt
```
Wiring: 2 spade terminals → pin 5 and pin 9, no polarity. If the button has an
LED, wire it to **5V (pin 2)** + GND so it lights whenever the Pi is powered.

## Access

- **SSH:** `ssh <SSH_USER>@<PI_IP_ETH>` (wired) / `<PI_IP>` (Wi-Fi). DHCP — reserve in the router if wanted. (Box currently runs Wi-Fi-only.)
- **Kodi web/phone remote:** `http://<ip>:8080` — user `<KODI_WEB_USER>`, password `<KODI_WEB_PASS>`.

---

## Software stack

### Base / network
- Raspberry Pi OS Lite / **Debian 13 (trixie)**, aarch64, kernel 6.18.
- Wi-Fi `<WIFI_SSID>` (auto-connect). **DNS `<LOCAL_DNS>`** primary so `<JELLYFIN_HOST>` resolves.

### Kodi (frontend)
- **Kodi 21.3 "Omega"**, headless on **GBM/DRM**, 1080p60. Autostarts via `kodi.service`; `getty@tty1` disabled. HDMI-CEC works (`cec0`).
- **Skin: Arctic Fuse 3** (`skin.arctic.fuse.3`, from the jurialmunkey repo) with all deps. A custom **remote-battery indicator** (icon + %) sits left of the clock (`1080i/Includes_Furniture.xml`; overwritten by skin updates — `.bak` kept). Temperature unit set to **°C**.
  - Arctic Fuse is heavy for a Pi 3. The lighter built-in **Estuary** is the fallback: `lookandfeel.skin` → `skin.estuary` in `~/.kodi/userdata/guisettings.xml` (also disable `plugin.video.themoviedb.helper`, which only AF3 needs).

### Jellyfin — `plugin.video.jellyfin` 2.1.0
- Installed manually (repo URLs were dead → repointed to `kodi.jellyfin.org/py3`; deps hand-placed from the Kodi Omega mirror).
- Server login: **`https://<JELLYFIN_HOST>`**, Add-on mode, libraries added via *Add libraries*.
- **⚠️ Playback gotchas (all fixed — keep these!):**
  1. **`syncDuringPlay = false`** — THE big one. With it on, the add-on scans the library *during* playback and crashes the video pipeline. Off = stable. (`~/.kodi/userdata/addon_data/plugin.video.jellyfin/settings.xml`)
  2. **`maxBitrate = 17` (20 Mbps)** — the Pi 3 can't decode 40+ Mbps REMUX; the cap makes the **server transcode** heavy files down (and downmix lossless audio). Lower to `6` (~4 Mbps/720p) if a title still struggles; raise/unlimited on a Pi 5.
  3. The Jellyfin **reverse proxy (`openresty`) cuts large direct streams at ~20 MB.** The bitrate cap sidesteps this (transcode = small HLS segments). To *direct-play* big files, point the add-on at the **direct server `http://<JELLYFIN_HOST_IP>:8096`** (bypasses the proxy) — best on a Pi 5.

### YouTube — `plugin.video.youtube` 7.4.4
- Installed with deps. Finish: sign in at **`google.com/device`**.

### Spotify — Raspotify (librespot)
- Spotify **Connect** device **"open-media"** (needs Premium). Config `/etc/raspotify/conf`.

### AirPlay audio — shairport-sync 4.3.7
- Always-on AirPlay **audio** as **"open-media"** (`_raop` :5000). No screen mirroring (Kodi owns the display). Config `/etc/shairport-sync.conf`.

### Siri Remote (A2854) — **working**
- Paired over BT (public addr `<REMOTE_MAC>`). Buttons arrive as GATT notifications on handle `0x0039`; touchpad motion (`0x003d`) and Siri voice (`0x0036`) are ignored.
- **Bridge:** [`kodi_siri_bridge.py`](scr/kodi_siri_bridge.py) → `~/a2854-siri-remote-linux/`, run by `kodi-siri-bridge.service` (root). It reads `btmon` and drives Kodi via JSON-RPC, and is **context-aware** (menu navigation vs. video seek/OSD). Also polls remote **battery** into `Window(Home).Property(SiriRemoteBattery)` + low-battery popup.
- Pairing tool `a2854_pair.py` was patched (auto-confirm passkey; accept public addresses; skip `sudo -v`).

**Button map** — menus: d-pad navigate · centre select · Back back · ⏯ play/pause · vol ± · Menu→Home · Power→CEC TV on/off.  During video: **d-pad seeks**, **centre opens OSD**, **Back stops**, **⏯ pauses**.

---

## Services
```bash
systemctl status kodi kodi-siri-bridge raspotify shairport-sync zramswap bt-fix
```
- `kodi.service` — Kodi (GBM), autostart.
- `kodi-siri-bridge.service` — the remote bridge.
- `bt-fix.service` — **boot fix for the RTL8761BU dongle**: reloads `btusb`, `rfkill unblock`, powers the adapter (the dongle fails its firmware download on the boot race). `/usr/local/bin/bt-fix.sh`.
- `zramswap` — compressed RAM swap (a `.d/reset.conf` drop-in makes it idempotent).

## Pi-3 stability tweaks
- **zram** swap (fast) instead of SD-card swap.
- `~/.kodi/userdata/advancedsettings.xml`: `imageres/fanartres 720` (caps texture memory), smaller video cache.
- `vm.swappiness=10` (`/etc/sysctl.d/99-swappiness.conf`).
- These are Pi-3 crutches — **not needed on a Pi 5** (the provisioning script skips them).

## Handy commands
```bash
tail -f ~/.kodi/temp/kodi.log                         # Kodi log
sudo rfkill unblock bluetooth                          # if BT dongle soft-blocked
sudo modprobe -r btusb btrtl && sudo modprobe btusb    # revive dongle manually
# repair a Kodi crash-loop: switch skin to Estuary in guisettings.xml
```

## Known limitations
- **Audio is shared** — Kodi, Spotify, AirPlay use the one HDMI output; one at a time.
- **Pi 3 is marginal for video** — works with the fixes above, but Arctic Fuse + high bitrate pushes it. **A Pi 5 removes all of this** (use `provision-pi5.sh`).

## Remaining / optional
- [ ] Fan final mount · 3D case print
- [ ] (Pi 5) restore full bitrate + point Jellyfin at `<JELLYFIN_HOST_IP>:8096` direct
