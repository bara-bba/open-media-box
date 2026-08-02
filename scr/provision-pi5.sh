#!/usr/bin/env bash
# =============================================================================
# Open Media Box — provisioning script
# Rebuilds the whole media-box stack on a FRESH Raspberry Pi OS Lite install.
# Target: Raspberry Pi 5 (uses onboard WiFi/BT — no USB dongles / bt-fix needed).
# Also works on Pi 3/4, but on those keep the USB dongles + see notes at the end.
#
# WHAT IT DOES (unattended):
#   - system update, installs Kodi + add-on tooling, Raspotify, shairport-sync
#   - Kodi runs headless on GBM/DRM, autostarts via systemd (kodi.service)
#   - installs add-ons: Jellyfin, YouTube, Arctic Fuse 3 (+ all dependencies)
#   - sets Arctic Fuse 3 as the skin, adds the top-bar remote-battery indicator
#   - installs the Siri Remote -> Kodi bridge (+ systemd service)
#   - configures Raspotify + shairport-sync as "open-media"
#
# STILL MANUAL AFTERWARDS (interactive, can't be scripted):
#   - Jellyfin: launch add-on -> log in -> Add libraries
#   - YouTube:  launch add-on -> sign in at google.com/device
#   - Siri Remote: pair it (see PAIRING note at the bottom)
#   - DNS for the internal Jellyfin name (see NETWORK note)
#
# USAGE:  copy to the Pi, then:  sudo bash provision-pi5.sh
# =============================================================================
set -euo pipefail

# Load config from .env (copy .env.example -> .env and fill it in).
# Looks next to this script and one level up (repo root).
for _envf in "$(dirname "$0")/.env" "$(dirname "$0")/../.env"; do
  if [ -f "$_envf" ]; then set -a; . "$_envf"; set +a; break; fi
done

USER_NAME="${SUDO_USER:-${SSH_USER:-pi}}"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
KODI_ADDONS="$USER_HOME/.kodi/addons"
KODI_USERDATA="$USER_HOME/.kodi/userdata"
WEB_USER="${KODI_WEB_USER:-kodi}"; WEB_PASS="${KODI_WEB_PASS:-changeme}"
JELLYFIN_SERVER="${JELLYFIN_URL:-https://jellyfin.example.com}"
SPOTIFY_NAME="${DEVICE_NAME:-open-media}"; AIRPLAY_NAME="${DEVICE_NAME:-open-media}"

say(){ echo -e "\n\033[1;36m== $* ==\033[0m"; }
krpc(){ curl -s --user "$WEB_USER:$WEB_PASS" -H 'Content-Type: application/json' \
        -d "$1" http://localhost:8080/jsonrpc; }

# -----------------------------------------------------------------------------
say "1/9  System update + packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y upgrade
apt-get -y install \
  kodi kodi-inputstream-adaptive kodi-inputstream-ffmpegdirect \
  kodi-eventclients-kodi-send \
  shairport-sync avahi-utils rfkill evtest \
  bluez libopus0 ffmpeg python3-venv git curl

# Raspotify (its own apt repo)
curl -sSL https://dtcooper.github.io/raspotify/key.asc \
  | tee /usr/share/keyrings/raspotify_key.asc >/dev/null
echo 'deb [signed-by=/usr/share/keyrings/raspotify_key.asc] https://dtcooper.github.io/raspotify raspotify main' \
  > /etc/apt/sources.list.d/raspotify.list
apt-get update
apt-get -y install raspotify

# -----------------------------------------------------------------------------
say "2/9  Kodi autostart service (GBM/DRM, 1080p)"
systemctl disable --now getty@tty1.service 2>/dev/null || true
cat > /etc/systemd/system/kodi.service <<EOF
[Unit]
Description=Kodi Media Center (standalone, GBM/DRM)
After=systemd-user-sessions.service network-online.target sound.target
Wants=network-online.target
[Service]
User=$USER_NAME
Group=$USER_NAME
SupplementaryGroups=input video render audio tty
PAMName=login
TTYPath=/dev/tty1
StandardInput=tty
StandardOutput=journal
StandardError=journal
ExecStart=/usr/bin/kodi-standalone
Restart=on-failure
RestartSec=5
TTYReset=yes
TTYVHangup=yes
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable kodi.service

# Generate a first guisettings.xml, then enable webserver + unknown sources
say "3/9  First Kodi boot to generate settings"
systemctl start kodi.service
sleep 25
systemctl stop kodi.service
sleep 3
GS="$KODI_USERDATA/guisettings.xml"
sed -i 's#<setting id="services.webserver"[^>]*>false</setting>#<setting id="services.webserver" default="false">true</setting>#' "$GS"
sed -i 's#<setting id="services.webserverpassword"[^/]*/>#<setting id="services.webserverpassword" default="false">'"$WEB_PASS"'</setting>#' "$GS"
sed -i 's#<setting id="addons.unknownsources"[^>]*>false</setting>#<setting id="addons.unknownsources" default="false">true</setting>#' "$GS"
chown "$USER_NAME:$USER_NAME" "$GS"

# -----------------------------------------------------------------------------
say "4/9  Download add-ons (Jellyfin, YouTube, Arctic Fuse 3 + deps)"
# NOTE: versions below are a working snapshot (2026-07). Bump if newer exist.
TMP=/tmp/omx-addons; rm -rf "$TMP"; mkdir -p "$TMP"; cd "$TMP"
KODI_MIRROR=https://mirrors.kodi.tv/addons/omega
JF=https://kodi.jellyfin.org/py3
JM=https://raw.githubusercontent.com/jurialmunkey/repository.jurialmunkey/master/omega/zips
get(){ curl -fsSL -o "$2" "$1" && echo "  ok $2" || echo "  FAIL $1"; }

# Jellyfin add-on + deps
get "$JF/plugin.video.jellyfin/plugin.video.jellyfin-2.1.0+py3.zip" jf.zip
for a in script.module.requests-2.31.0 script.module.urllib3-2.2.3 \
         script.module.idna-3.10.0 script.module.chardet-5.1.0 \
         script.module.certifi-2023.5.7 script.module.six-1.16.0+matrix.1 \
         script.module.dateutil-2.8.2 script.module.addon.signals-0.0.6+matrix.1 \
         script.module.websocket-1.6.4 script.module.pysocks-1.7.0+matrix.1 \
         script.module.inputstreamhelper-0.8.5 script.module.qrcode-6.1.0+matrix.3; do
  id="${a%-*}"; get "$KODI_MIRROR/$id/$a.zip" "$a.zip"; done
# YouTube
get "$KODI_MIRROR/plugin.video.youtube/plugin.video.youtube-7.4.4.zip" yt.zip
# Arctic Fuse 3 + JM deps
get "$JM/skin.arctic.fuse.3/skin.arctic.fuse.3-3.2.14.zip" af.zip
for a in script.module.infotagger-0.0.8 script.module.jurialmunkey-0.2.35 \
         script.skinvariables-2.2.2 script.texturemaker-0.2.11 \
         plugin.video.themoviedb.helper-6.16.2 resource.font.robotocjksc-0.0.3; do
  id="${a%-*}"; get "$JM/$id/$a.zip" "$a.zip"; done
for a in resource.images.weathericons.white-0.0.6 resource.images.studios.coloured-0.0.24; do
  id="${a%-*}"; get "$KODI_MIRROR/$id/$a.zip" "$a.zip"; done
# Jellyfin repo add-on, URL-fixed to the live py3 mirror
curl -fsSL -o repo.zip https://kodi.jellyfin.org/py3/repository.jellyfin.kodi.zip

say "5/9  Extract add-ons into Kodi"
mkdir -p "$KODI_ADDONS"
for z in "$TMP"/*.zip; do python3 -c "import zipfile,sys;zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$z" "$KODI_ADDONS"; done
# fix the Jellyfin repo add-on URLs to the working location
sed -i 's#https://repo.jellyfin.org/releases/client/kodi#https://kodi.jellyfin.org/py3#g' \
  "$KODI_ADDONS/repository.jellyfin.kodi/addon.xml" 2>/dev/null || true
chown -R "$USER_NAME:$USER_NAME" "$KODI_ADDONS"

# -----------------------------------------------------------------------------
say "6/9  Start Kodi and enable add-ons"
systemctl start kodi.service
sleep 25
for a in script.module.requests script.module.urllib3 script.module.idna \
         script.module.chardet script.module.certifi script.module.six \
         script.module.dateutil script.module.addon.signals script.module.websocket \
         script.module.pysocks script.module.inputstreamhelper script.module.qrcode \
         script.module.infotagger script.module.jurialmunkey script.skinvariables \
         script.texturemaker resource.font.robotocjksc \
         resource.images.weathericons.white resource.images.studios.coloured \
         plugin.video.themoviedb.helper plugin.video.jellyfin plugin.video.youtube \
         skin.arctic.fuse.3; do
  krpc '{"jsonrpc":"2.0","id":1,"method":"Addons.SetAddonEnabled","params":{"addonid":"'"$a"'","enabled":true}}' >/dev/null
  echo "  enabled $a"
done

# -----------------------------------------------------------------------------
say "7/9  Set Arctic Fuse 3 skin + battery indicator + Celsius"
systemctl stop kodi.service; sleep 3
sed -i 's#<setting id="lookandfeel.skin"[^>]*>skin.estuary</setting>#<setting id="lookandfeel.skin" default="false">skin.arctic.fuse.3</setting>#' "$GS"
# battery icon + % left of the clock in the header
FUR="$KODI_ADDONS/skin.arctic.fuse.3/1080i/Includes_Furniture.xml"
if [ -f "$FUR" ] && ! grep -q SiriRemoteBattery "$FUR"; then
python3 - "$FUR" <<'PY'
import sys
f=sys.argv[1]; s=open(f,encoding='utf-8').read()
i=s.index('$INFO[System.Time]$VAR[Furniture_Header_Right_Temperature')
start=s.rindex('<control type="label">',0,i); end=s.index('</control>',i)+len('</control>')
gl='''<control type="grouplist">
                <right>0</right><top>0</top><width>720</width><height>80</height>
                <align>right</align><orientation>horizontal</orientation><itemgap>12</itemgap>
                <control type="image"><width>64</width><height>80</height>
                    <aspectratio aligny="center">keep</aspectratio>
                    <texture>$VAR[Furniture_BatteryIcon]</texture>
                    <colordiffuse>$PARAM[textcolor]</colordiffuse>
                    <visible>!String.IsEmpty(Window(Home).Property(SiriRemoteBatteryLevel))</visible></control>
                <control type="label"><width>auto</width><height>80</height>
                    <label>$INFO[Window(Home).Property(SiriRemoteBattery)]</label>
                    <aligny>center</aligny><textcolor>$PARAM[textcolor]</textcolor><font>font_midi_bold</font>
                    <visible>!String.IsEmpty(Window(Home).Property(SiriRemoteBattery))</visible></control>
                <control type="label"><width>auto</width><height>80</height>
                    <label>$INFO[System.Time]$VAR[Furniture_Header_Right_Temperature, • ,]</label>
                    <aligny>center</aligny><textcolor>$PARAM[textcolor]</textcolor><font>font_midi_bold</font></control>
            </control>'''
s=s[:start]+gl+s[end:]
tv='<value condition="!Skin.HasSetting(Header.DisableWeather)">$INFO[Weather.Temperature]</value>\n    </variable>'
s=s.replace(tv, tv+'''

    <variable name="Furniture_BatteryIcon">
        <value condition="Integer.IsGreater(Window(Home).Property(SiriRemoteBatteryLevel),87)">special://skin/extras/icons/battery-full.png</value>
        <value condition="Integer.IsGreater(Window(Home).Property(SiriRemoteBatteryLevel),62)">special://skin/extras/icons/battery-three-quarters.png</value>
        <value condition="Integer.IsGreater(Window(Home).Property(SiriRemoteBatteryLevel),37)">special://skin/extras/icons/battery-half.png</value>
        <value condition="Integer.IsGreater(Window(Home).Property(SiriRemoteBatteryLevel),12)">special://skin/extras/icons/battery-quarter.png</value>
        <value>special://skin/extras/icons/battery-empty.png</value>
    </variable>''',1)
open(f,'w',encoding='utf-8').write(s)
print("  battery indicator added to skin")
PY
fi
# Celsius
sed -i 's#<setting id="locale.temperatureunit"[^>]*>[^<]*</setting>#<setting id="locale.temperatureunit" default="false">\xc2\xb0C</setting>#' "$GS"
chown "$USER_NAME:$USER_NAME" "$GS"

# -----------------------------------------------------------------------------
say "8/9  Raspotify + shairport-sync (both named '$SPOTIFY_NAME')"
# Detect the HDMI ALSA card. Pi 3/4 have one card named "vc4hdmi"; Pi 5 has
# two ("vc4hdmi0"/"vc4hdmi1", one per micro-HDMI port) — prefer whichever one
# actually has a display attached (non-empty ELD monitor_name), else just
# take the first vc4hdmi* card found.
HDMI_CARD=""
for f in /proc/asound/card*/eld*; do
  name=$(grep -m1 '^monitor_name' "$f" 2>/dev/null | awk '{$1="";print}' | xargs)
  [ -z "$name" ] && continue
  n=$(echo "$f" | sed -E 's#.*/card([0-9]+)/.*#\1#')
  HDMI_CARD=$(aplay -l | awk -v n="$n" '$0 ~ "^card "n":" {print; exit}' \
              | sed -E 's/^card [0-9]+: ([^ ]+).*/\1/')
  break
done
[ -z "$HDMI_CARD" ] && HDMI_CARD=$(aplay -l | grep -oE 'vc4hdmi[0-9]*' | head -1)
[ -z "$HDMI_CARD" ] && HDMI_CARD="vc4hdmi"
ALSA_DEVICE="plughw:CARD=${HDMI_CARD},DEV=0"
say "   using ALSA device: $ALSA_DEVICE"

if ! grep -q "^LIBRESPOT_NAME=\"$SPOTIFY_NAME\"" /etc/raspotify/conf 2>/dev/null; then
cat >> /etc/raspotify/conf <<EOF

# --- Open Media Box ---
LIBRESPOT_NAME="$SPOTIFY_NAME"
LIBRESPOT_DEVICE_TYPE="avr"
LIBRESPOT_BACKEND="alsa"
LIBRESPOT_DEVICE="$ALSA_DEVICE"
LIBRESPOT_BITRATE="320"
LIBRESPOT_INITIAL_VOLUME="80"
EOF
fi
systemctl restart raspotify

# Edit shairport-sync's shipped config IN PLACE (its libconfig format
# rejects a second top-level "general"/"alsa" block, so appending an
# override group — the old approach — fails with "duplicate setting name").
# These sed patterns match the package's default commented-out lines, so
# they're safe to re-run (a no-op once already applied).
sed -i 's#^//\s*name = "%H";.*#\tname = "'"$AIRPLAY_NAME"'"; // set by provisioning#' /etc/shairport-sync.conf
sed -i '0,/^\/\/\s*output_backend = /{s#^//\s*output_backend = "alsa";.*#\toutput_backend = "alsa"; // set by provisioning#}' /etc/shairport-sync.conf
sed -i 's#^//\s*output_device = "default";.*#\toutput_device = "'"$ALSA_DEVICE"'"; // set by provisioning#' /etc/shairport-sync.conf
systemctl enable --now shairport-sync
systemctl restart shairport-sync || true

# -----------------------------------------------------------------------------
say "9/9  Siri Remote bridge"
BR="$USER_HOME/a2854-siri-remote-linux"
sudo -u "$USER_NAME" git clone --depth 1 https://github.com/henaxxx/a2854-siri-remote-linux.git "$BR" 2>/dev/null || true
# NOTE: the kodi_siri_bridge.py is shipped alongside this script — copy it in:
if [ -f "$(dirname "$0")/kodi_siri_bridge.py" ]; then
  cp "$(dirname "$0")/kodi_siri_bridge.py" "$BR/kodi_siri_bridge.py"
  chown "$USER_NAME:$USER_NAME" "$BR/kodi_siri_bridge.py"
fi
cat > /etc/systemd/system/kodi-siri-bridge.service <<EOF
[Unit]
Description=Siri Remote (A2854) -> Kodi bridge
After=bluetooth.service kodi.service network-online.target
[Service]
Type=simple
Environment=REMOTE_MAC=${REMOTE_MAC:-AA:BB:CC:DD:EE:FF}
Environment=KODI_WEB_USER=$WEB_USER
Environment=KODI_WEB_PASS=$WEB_PASS
ExecStart=/usr/bin/python3 $BR/kodi_siri_bridge.py
Restart=always
RestartSec=3
TimeoutStopSec=5
User=root
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable kodi-siri-bridge.service   # starts working once the remote is paired

# Arcade power button on GPIO3 (pin 5) + GND: press-while-off boots the Pi,
# press-while-running does a clean shutdown. Takes effect after a reboot.
CONFIG_TXT=/boot/firmware/config.txt
grep -q '^dtoverlay=gpio-shutdown' "$CONFIG_TXT" || echo 'dtoverlay=gpio-shutdown' >> "$CONFIG_TXT"

# Appliance-style boot: no rainbow test square, no scrolling kernel log, no
# blinking console cursor — the box goes from black straight to Kodi's splash.
grep -q '^disable_splash=1' "$CONFIG_TXT" || echo 'disable_splash=1' >> "$CONFIG_TXT"

# The Pi 5's onboard Broadcom BT connects to an Apple Siri Remote (A2854) but
# drops the link ~100ms later without a single SMP frame, so it can never bond.
# A Realtek RTL8761BU USB dongle pairs it first try. Disable the onboard radio
# so the dongle is the only adapter. (Harmless if you use no Siri Remote —
# comment out to keep onboard Bluetooth.)
grep -q '^dtoverlay=disable-bt' "$CONFIG_TXT" || echo 'dtoverlay=disable-bt' >> "$CONFIG_TXT"
CMDLINE=/boot/firmware/cmdline.txt
if [ -f "$CMDLINE" ]; then
  python3 - "$CMDLINE" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read().strip()
for flag in ("quiet", "loglevel=0", "logo.nologo",
             "vt.global_cursor_default=0", "splash"):
    if flag.split("=")[0] not in s:
        s += " " + flag
open(p, "w").write(s + "\n")
PY
fi

systemctl start kodi.service

cat <<DONE

=============================================================================
 BASE SETUP COMPLETE.  Reboot, then finish these interactive steps:

 Control the box now via TV remote (HDMI-CEC) or the web remote:
     http://<pi-ip>:8080     user: kodi   pass: kodi

 1) JELLYFIN:  open the Jellyfin add-on -> log in to your server
    ($JELLYFIN_URL , or direct $JELLYFIN_DIRECT to
    bypass the reverse proxy) -> "Add libraries" -> pick Movies/TV.
    (Set your DNS so the internal name resolves — see NETWORK note.)
    Then in the add-on's settings.xml (addon_data/plugin.video.jellyfin/):
      - syncDuringPlay=false   <-- IMPORTANT: library sync during playback
                                    crashes video; keep it off.
      - maxBitrate: only needed on a weak box (Pi 3). On a Pi 5 leave it
        unlimited (23) to direct-play everything.
 2) YOUTUBE:   open the YouTube add-on -> sign in at google.com/device.
 3) SIRI REMOTE: pair it, then put its MAC in .env (REMOTE_MAC), re-run
    this script (or edit the service's Environment=REMOTE_MAC), and restart:
        cd ~/a2854-siri-remote-linux
        python3 a2854_pair.py --pair --seconds 100 --min-rssi -55
        # hold Back + Volume-Up on the remote, on top of the BT adapter
        sudo systemctl restart kodi-siri-bridge.service

 NETWORK: point DNS at your local resolver so $JELLYFIN_URL resolves,
   e.g.:  sudo nmcli con mod <conn> ipv4.dns $LOCAL_DNS ipv4.dns-priority -10
          sudo nmcli con up <conn>

 PI 5 vs PI 3: on the Pi 5 the onboard WiFi/BT work, so you do NOT need the
   USB dongles, the 'dtoverlay=disable-bt' line, the bt-fix service, or the
   zram / low-RAM tweaks that the Pi 3 needed.
=============================================================================
DONE
