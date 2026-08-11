# Open Media Box — Setup & Operation

**boxy** — a Raspberry Pi 5 (2 GB) running Kodi as an open-source media box:
1080p HDMI, streams Jellyfin / YouTube / Spotify (in-Kodi) / AirPlay audio,
controlled by an Apple Siri Remote, the TV remote (HDMI-CEC), or a phone.
Migrated off the original Pi 3 ("open-media") in August 2026 — that box is
retired; see the bottom of this doc for what changed.

This documents what was actually built. Design rationale + task list: [`plan.md`](plan.md).
Rebuild-on-a-new-Pi script: [`provision-pi5.sh`](scr/provision-pi5.sh) (+ [`kodi_siri_bridge.py`](scr/kodi_siri_bridge.py)).

> **Config:** values shown as `<PLACEHOLDER>` (IPs, Wi-Fi SSID, Kodi password,
> remote MAC) are your own — copy [`.env.example`](.env.example) to `.env`
> (gitignored) and fill them in. The scripts read them from there.

> **⚠️ Provisioning gap:** several things below were set up *live on boxy*,
> not yet folded back into `provision-pi5.sh` — a from-scratch rebuild would
> currently need these done by hand again:
> - `bt-fix.service` (RTL8761BU dongle boot-race fix, see [Siri Remote](#siri-remote-a2854--working))
> - `plugin.audio.spotify` install + its personal API/OAuth-free zeroconf pairing
> - `plugin.video.youtube` personal API keys + OAuth sign-in
> - The Arctic Fuse header edits (CPU temp, battery, clock) and the Spotify/YouTube custom home tabs
> - `systemd-logind` power-key config (see [Power button](#power-button))

---

## Hardware

| Part | Detail |
|---|---|
| Board | Raspberry Pi 5 (2 GB) |
| Wi-Fi | Onboard (Wi-Fi is fine on the 5; a wired connection is available too) |
| Bluetooth | ASUS USB-BT500 (Realtek **RTL8761BU**) — **onboard Pi 5 BT cannot bond with the Siri Remote at all** (see below), so onboard BT is disabled and the dongle is the only adapter |
| Storage / PSU | microSD, official 27 W USB-C PSU |
| Output | HDMI 1080p60 to TV |
| Power button | Arcade (momentary) switch wired to the **Pi 5's dedicated 2-pin power header** (not GPIO — the 5 has a real onboard power connector near the PCIe FPC slot) |

### Power button
Unlike the Pi 3/4, the Pi 5 has a **dedicated power-button header**, wired
into the board's PMIC directly — no GPIO overlay needed. It shows up to
Linux as a normal input device (`pwr_button`, `gpio-keys`) and is handled by
`systemd-logind`:

```bash
# /etc/systemd/logind.conf
HandlePowerKey=poweroff          # short press: clean shutdown
HandlePowerKeyLongPress=reboot   # long press (~4s+): force reboot if Kodi/UI is hung
```
```bash
sudo systemctl restart systemd-logind   # apply without a reboot
```
- **Press while off** → powers the board on (handled by the PMIC itself, no OS involvement).
- **Short press while running** → clean shutdown.
- **Long press while running** → force reboot via systemd (works if the OS is alive but Kodi is hung).
- **Hold ~10s+** → hardware-level forced power-off, independent of the OS —
  the PMIC's own failsafe, works even if the kernel itself is wedged. Press
  again afterward to power back on.

## Access

- **SSH:** `ssh -i ~/.ssh/ombx_pi barbara@<PI_IP>` (key auth only, plain `ssh` fails — non-default key). Passwordless sudo.
- **Kodi web/phone remote:** `http://<PI_IP>:8080` — user/pass `kodi`.

---

## Software stack

### Base / network
- Raspberry Pi OS Lite / **Debian 13 (trixie)**, aarch64, kernel 6.18.
- **zram** compressed swap is active out of the box on this image (2 GB, `/dev/zram0`) — no manual setup needed, unlike the Pi 3 which needed it added.

### Kodi (frontend)
- **Kodi 21.3 "Omega"**, headless on **GBM/DRM** (no X11/Wayland), 1080p60. Autostarts via `kodi.service`. HDMI-CEC works.
- **Skin: Arctic Fuse 3** (`skin.arctic.fuse.3`, jurialmunkey repo), comfortable on the 5 (was too heavy for the Pi 3).
  - Custom header (`1080i/Includes_Furniture.xml`): remote battery icon+%, CPU-temp icon+reading, clock, weather — all **live-edited into the skin's own files**, wiped by a skin update (`.bak*` copies kept, not yet ported into provisioning).
  - Boot splash replaced with plain black (`/usr/share/kodi/media/splash.jpg`, original backed up as `.orig`) — no logo at all during boot.
  - **Two custom Home-menu tabs** built via the skin's own shortcuts editor (long-press/context-menu on a Home tile → configure), each a full hub page with its own icon and content rows — see Spotify/YouTube sections below.

### Jellyfin — `plugin.video.jellyfin`
- Server login via Add-on mode, libraries added via *Add libraries*.
- **`syncDuringPlay = false`** is essential — library sync during playback crashes the video pipeline. (`~/.kodi/userdata/addon_data/plugin.video.jellyfin/settings.xml`)
- The Pi 5 has enough headroom that the Pi-3-era bitrate cap and direct-server workaround are **not needed** — full bitrate works fine.

### YouTube — `plugin.video.youtube` 7.4.4
Google deprecated the shared/default API keys this addon used to ship with —
**every install now needs its own Google Cloud credentials**, all three of:
- an **API key** (Credentials → Create Credentials → API key)
- an **OAuth Client ID + Secret** (type: *TVs and Limited Input devices*)
- **YouTube Data API v3 enabled** for the project

Entered in the addon's own settings (`youtube.api.key` / `youtube.api.id` /
`youtube.api.secret` — all three or none; a partial set is silently ignored
and the addon falls back to a broken default). The three values also live in
`~/.kodi/userdata/addon_data/plugin.video.youtube/api_keys.json`.

**Critical, easy-to-miss step:** the OAuth consent screen for that Google
Cloud project must have your Google account added under **Test users** (if
the app is in "Testing" publish status — which it will be) and have a
YouTube scope actually added under Scopes. Skipping this produces `Error
403: access_denied` on sign-in, or "Invalid or disabled client" on every API
call even with a technically-valid access token — this bit us for a while.

Sign-in itself is the standard device-code flow (addon shows a code + a
`google.com/device`-style URL — approve on your phone). Changing the
API/OAuth credentials does **not** auto-invalidate old sign-in tokens; you
must explicitly Sign Out then Sign In again after any credential change, or
you'll keep hitting "invalid client" against stale tokens.

**Home tab** (`1102`, icon `youtube.png`): rows for *Recommendations* and
*Subscribed Channels* (needs the OAuth half above — an API key alone only
grants access to public data like Trending/Search, never anything tied to
your account).

### Spotify — `plugin.audio.spotify` 1.3.14 (glk1001 fork)
**Not raspotify anymore.** The original design (raspotify + a Web API bridge
pausing/resuming it to arbitrate HDMI audio with Kodi) was fragile — rate
limiting, race conditions on device handover, boxy randomly vanishing from
the phone's Spotify device list — and was fully removed in favor of this
native Kodi addon.

- The upstream `marcelveldt/repository.marcelveldt` addon (what most
  tutorials point to) is dead on Kodi 21 — its `addon.xml` still targets
  Python 2 (Kodi ≤18). **Use the `glk1001` fork instead**
  (`https://glk1001.github.io`), actively maintained for Kodi 19–21.
- Ships no native aarch64-Linux `spotty` binary (only x86_64 and 32-bit
  armhf) — falls back to the armhf-musl static binary, which runs fine under
  the Pi 5 kernel's 32-bit compat mode. Confirmed working, not a blocker.
- **Architecture shift, worth understanding:** this addon is an **in-Kodi
  Spotify browser/player**, not a persistent Spotify Connect receiver.
  Zeroconf/Connect discoverability ("boxy" showing up in your phone's
  Spotify app) only happens *once*, during the initial pairing handshake —
  after that there's no persistent Connect listener running, so it will
  **not** show up as a castable device in normal use. You browse
  playlists/tracks directly in Kodi and it plays through Kodi's own player
  (spotty as the audio backend) — decided deliberately to keep this
  (see the doc's history) rather than reinstating a Connect receiver
  alongside it, which would bring back the HDMI-audio-arbitration
  complexity described under [AirPlay](#airplay-audio--shairport-sync).
- Cover art gotcha: the skin's default **Landscape** row style prioritizes
  `Art(fanart)` over `Art(thumb)`, and this addon sets the same static
  branding fanart on every item — so every row item showed the identical
  placeholder image regardless of real per-item art. Fixed by setting
  **`"widget_style": "Square"`** on each row (uses `Art(poster)`→`Icon`
  instead, and `Icon` correctly falls back to the real thumb).
- Addon's own stock branding fanart (an old-looking stock photo) replaced
  with a generated modern placeholder matching the current Spotify logo
  (`resources/fanart.jpg`, original backed up as `.orig-old-photo`) — also
  required manually purging the stale cached copy from Kodi's
  `Textures13.db`/`Thumbnails/` after replacing the file, since Kodi caches
  local-path textures indefinitely otherwise.

**Home tab** (`1101`, icon `spotify.png`): rows for *Made For You*
("Realizzata per te"), *New Releases*, *Playlists*, *Followed Artists* — all
`widget_style: Square`, `widget_limit: 20`. Row config lives in
`~/.kodi/userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3/skinvariables-shortcut-1101widgets.json`.

> **⚠️ 2 GB RAM is tight.** Adding too many simultaneous plugin-backed rows
> (tried 9 at once, each fetching metadata + cover art) reliably crashed the
> whole box — not just Kodi, SSH itself became unresponsive, consistent
> with heavy swap thrashing. Keep row counts modest (we settled on 4) and
> add new ones one at a time, watching `free -h`, rather than bulk-editing.
> zram is already active and doesn't fully save you from this.

> **Editor quirk:** hand-editing the `skinvariables-shortcut-*.json` files
> directly doesn't reliably take effect — the skin's widget-editor GUI seems
> to hold its own in-memory state that overwrites file changes on save if
> the editor was already open. Safest path: edit the file, then do a
> **fresh** open of the in-Kodi widget editor (not a resumed session) and
> save once to force the regenerate.

### AirPlay audio — shairport-sync
Always-on AirPlay audio as "boxy" (`_raop` :5000). The Pi 5's `vc4-hdmi`
output only supports `IEC958_SUBFRAME_LE`, so ALSA dmix can't mix — one
process owns the device at a time. `kodi_siri_bridge.py`'s
`enforce_kodi_priority()` stops `shairport-sync` while Kodi is **actively
playing** (`Player.GetProperties.speed != 0`) and restarts it once Kodi goes
idle, so AirPlay is available whenever you're just browsing menus. Since
Spotify moved in-Kodi (see above), this is now **AirPlay-only** arbitration
— no more three-way Kodi/Spotify/AirPlay juggling.

- Correct Kodi audio device: **`ALSA:sysdefault:CARD=vc4hdmi0`** (the
  `hdmi:CARD=...` variant adds AES params vc4-hdmi rejects and silently
  falls back to a nonexistent headphone jack). Pi 5 has *two* HDMI cards
  (`vc4hdmi0`/`vc4hdmi1`) — never hardcode; auto-detect via ELD
  `monitor_name` in `/proc/asound/card*/eld*`.
- `audiooutput.streamsilence` was set to `0` ("never keep alive") so Kodi
  fully released the HDMI device the instant it went idle — but this made
  **every isolated UI navigation click silent** (single clicks arrived
  before the freshly-reopened ALSA sink was ready; rapid clicks worked
  because they reused the still-open device). Changed to a **1-minute
  keep-alive** instead, trading a narrow AirPlay-blocked window
  (≤60s after the last click) for reliable UI sound — acceptable since
  `enforce_kodi_priority()` already handles the main case (active playback)
  explicitly.

### Siri Remote (A2854) — working
- **The Pi 5's onboard Bluetooth cannot bond with this remote at all** —
  confirmed via raw `btmon` HCI capture: it connects then drops the link
  ~100 ms later with zero SMP frames exchanged. Not a config issue, a
  hardware/driver limitation. Fixed by disabling onboard BT
  (`dtoverlay=disable-bt` in `/boot/firmware/config.txt`) and using the
  RTL8761BU USB dongle exclusively — bonds on the first try.
- **RTL8761BU boot race:** the dongle loads its firmware but comes up
  finding zero devices on a cold boot (same class of bug seen on the old
  Pi 3). Fixed with `bt-fix.service` (`/usr/local/bin/bt-fix.sh`): reloads
  `btusb`/`btrtl`, `rfkill unblock`, `btmgmt power on`. **Not yet ported
  into `provision-pi5.sh`** — created live on boxy only.
- **Bridge:** [`kodi_siri_bridge.py`](scr/kodi_siri_bridge.py) →
  `~/a2854-siri-remote-linux/`, run by `kodi-siri-bridge.service` (root).
  Reads `btmon`, drives Kodi via JSON-RPC, context-aware (menu nav vs.
  video seek/OSD). Polls battery into
  `Window(Home).Property(SiriRemoteBattery)`, shows connect/disconnect
  toast notifications with skin icons.
- **Never cycle a fresh BT bond.** The bridge's re-arm (disconnect/
  reconnect) logic once destroyed a just-created bond — the remote kept its
  keys, BlueZ lost its own, unrecoverable without resetting the remote.
  Guarded with `BOND_SETTLE_SECS=300` now, but worth remembering if this
  code is touched again.

**Button map** — menus: d-pad navigate · centre select · Back back · ⏯
play/pause · vol ± · Menu→Home · Power→CEC TV on/off. During video: **d-pad
seeks**, **centre opens OSD**, **Back stops**, **⏯ pauses**.

---

### Live TV — Dispatcharr + Jellyfin + Kodi
**This lives on a different machine** — `servarr` (192.168.1.68), the same
Docker host running Jellyfin and the rest of the `*arr` stack — not on boxy
itself. boxy's Kodi is just a client of it. Setup reference:
[`setup-dispatcharr.sh`](scr/setup-dispatcharr.sh) (prints the compose block
to add; doesn't auto-patch `compose.yaml` since that file is hand-maintained
and heavily commented — a YAML-library rewrite would strip all of it).

**Dispatcharr** (`ghcr.io/dispatcharr/dispatcharr`, all-in-one image) manages
IPTV M3U sources + XMLTV guide data and re-exposes a curated channel list as
its own M3U/EPG endpoints (and an HDHomeRun-emulated tuner). It's a
management/proxy layer — it needs a real upstream IPTV source, it doesn't
generate content.

- **Deliberately not VPN-routed.** Tried `network_mode: service:gluetun`
  first — Rai's streams (and likely other Italian broadcasters) started
  failing immediately, and it turned out to be unrelated to geography: Akamai
  (Rai's CDN) blocks known commercial VPN IP ranges outright, regardless of
  the exit country being correctly set to Italy. IPTV needs your real
  residential IP; reverted to Dispatcharr on its own `servarrnetwork` address
  instead.
- **DNS matters.** Italy's ISP-level anti-piracy DNS blocking ("Piracy
  Shield") has a real history of over-blocking, and was seen incorrectly
  affecting `mediapolis.rai.it` — Rai's *own* legitimate relinker domain —
  on the host's default resolver. Setting the container's `dns:` to
  `1.1.1.1`/`1.0.0.1` fixed it. Confirmed via direct `curl` testing before
  touching Docker at all: same URL failed via default DNS, worked via
  `1.1.1.1`, worked via the VPN (different reason, see above) — isolating
  DNS as the actual variable.
- **Provenance matters more than "does it play."** Public aggregator M3U
  lists (`iptv-org/iptv`, `Free-TV/IPTV`) mix legitimately-sourced channels
  (pointing at the broadcaster's own domain — `mediapolis.rai.it`,
  `originstream12.rai.it`, Al Jazeera's `getaj.net`) with unauthorized
  restreams on generic third-party reseller/CDN domains. A stream working
  has nothing to do with whether it's licensed — checked per-channel by
  looking at which domain it actually points to, not by whether it loads.
  One entry (`streamhostingcdn.top`, an old Rai Sport mirror) turned out to
  be DNS-sinkholed to `0.0.0.0` by Italian ISP blocking — a real anti-piracy
  block, left alone rather than routed around.
- **Rai's relinker (`mediapolis.rai.it/relinker/relinkerServlet.htm`) needs
  a live resolve, not a static URL.** Requires a `Referer:
  https://www.raiplay.it/` header (else `403` from Akamai) and an
  `output=64` query param (else an empty `<Mediapolis>` response) to return
  the actual stream — and that returned URL is a **signed token that
  expires in 5 minutes** (`hdnea=st=...~exp=...`). Every Rai channel in the
  public M3U lists uses this same mechanism (just a different `cont=` ID
  each), so none of them work as a plain static M3U entry long-term — they
  all need periodic re-resolution. **Not yet built**: a small timed
  resolver script to keep Rai channels alive in Dispatcharr; currently an
  open item, not a solved one.
- **EPG (`tvit`, `https://tvit.leicaflorianrobert.dev/epg/list.xml`) turned
  out to be a dead end for programme data**, despite being branded for
  Italy: it defines dozens of Italian channels (logos, IDs) but the actual
  `<programme>` entries in the file are 100% Romanian channels — zero
  schedule data for any Italian channel. Channel-level EPG matching
  succeeds (looks assigned in Dispatcharr) while the guide stays empty —
  that's a source-data gap, not a Dispatcharr bug. Need a different EPG
  source; not yet found one that actually has Italian programme data.
- **Kodi's PVR side**: `pvr.iptvsimple`, pointed at Dispatcharr's own M3U +
  EPG output. On Linux, Kodi binary PVR/inputstream addons come from the
  **OS package manager, not Kodi's in-app zip repo** — `mirrors.kodi.tv`'s
  addons.xml only lists Windows/macOS/Android builds for this addon, no
  Linux ones. Install via `apt install kodi-pvr-iptvsimple` (already in
  `provision-pi5.sh`), not through Kodi's Add-on browser.
- **`pvr.jellyfin`/"Kofin"** (a PVR client that would surface Jellyfin's
  Live TV natively in Kodi, rather than Kodi hitting Dispatcharr directly)
  exists but is source-only (C++, CMake build, no prebuilt zip/repo found)
  — skipped rather than attempting an on-device compile on a memory-tight
  2 GB board. Kodi currently talks to Dispatcharr directly instead of
  through Jellyfin.
- **Jellyfin Live TV integration: unresolved.** Tuner added (M3U pointed at
  Dispatcharr's output) but channels aren't appearing after a guide
  refresh — not yet root-caused, needs checking whether Jellyfin's tuner
  scan itself is failing vs. a guide-mapping issue.

## Services
```bash
systemctl status kodi kodi-siri-bridge shairport-sync bt-fix avahi-daemon
```
- `kodi.service` — Kodi (GBM), autostart.
- `kodi-siri-bridge.service` — the remote bridge + AirPlay/Kodi audio arbitration.
- `bt-fix.service` — boot fix for the RTL8761BU dongle (see Siri Remote above). **Not yet in provisioning script.**
- `avahi-daemon` — mDNS, needed for AirPlay discovery and Spotify's one-time zeroconf pairing.
- `raspotify` — **removed**, disabled and stopped, no longer installed as part of this stack.

## Handy commands
```bash
tail -f ~/.kodi/temp/kodi.log                          # Kodi log
sudo systemctl restart kodi                             # clean Kodi restart (settings only persist on clean exit)
sudo modprobe -r btusb btrtl && sudo modprobe btusb     # revive the BT dongle manually if bt-fix.service didn't run
free -h                                                  # check memory before adding more widget rows
```

## Known limitations
- **2 GB RAM is genuinely tight** with Kodi + Arctic Fuse + TMDbHelper +
  Jellyfin + Spotify + YouTube all installed — see the Spotify section's
  crash warning. Budget carefully before adding more addons/widgets.
- **HDMI audio is still shared** between Kodi and AirPlay (Spotify moved
  in-Kodi so it's out of this contention now) — one at a time, arbitrated
  by the bridge.
- Several live-on-boxy changes aren't yet folded into `provision-pi5.sh` —
  see the gap list at the top of this doc.

## Remaining / optional
- [ ] Port `bt-fix.service`, the Spotify/YouTube addon installs, and the
      skin header/tab edits into `provision-pi5.sh` for a clean rebuild
- [ ] Investigate "only a few clicks are audible" residue, if it recurs
      after the `streamsilence` change
- [ ] Push the local repo (currently unpushed, ahead of `origin/main`)

---

## History: migration from the Pi 3
The original "open-media" Pi 3 build (1 GB, Realtek Wi-Fi/BT USB dongles,
zram + swappiness + reduced texture-cache tweaks to survive Arctic Fuse,
Estuary as a fallback skin) is retired. Its README content has been
superseded by this doc; the old constraints (bitrate caps, Pi-3 stability
tweaks, GPIO3 power button) don't apply to the Pi 5 and have been removed
above rather than kept as dead weight.
