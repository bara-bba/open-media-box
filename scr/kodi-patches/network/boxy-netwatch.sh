#!/bin/sh
# Wi-Fi self-heal. NetworkManager can mark the connection "failed" after a router
# re-key (4-way handshake lost -> "no secrets" -> never retries) and stay offline
# until a power cycle. Run every 20 s by boxy-netwatch.timer (check counts below are therefore *20 s):
#   9 failed checks (~3 min) -> toggle Wi-Fi and reconnect
#   18 (~6 min)              -> restart NetworkManager
#   36 (~12 min)             -> reboot (at most once every 6 h)
STATE=/run/boxy-netwatch
LASTREBOOT=/var/lib/boxy-netwatch/last-reboot
mkdir -p "$STATE" /var/lib/boxy-netwatch

gw=$(ip route show default 2>/dev/null | awk '/^default/ {print $3; exit}')
dev=$(ip route show default 2>/dev/null | awk '/^default/ {print $5; exit}')
# header icon: exactly one of wifi / ethernet / down (shown by the skin via Window(Home).Property(NetType))
publish(){ kodi-send --action="SetProperty(NetType,$1,home)" >/dev/null 2>&1; }
# The YouTube add-on caches "no internet"/empty results; after an outage it can stay
# "not logged in" until those caches are cleared. Clear them (cache only, sign-in is kept).
clear_youtube_cache(){
  for db in /home/*/.kodi/userdata/addon_data/plugin.video.youtube/*/cache.sqlite             /home/*/.kodi/userdata/addon_data/plugin.video.youtube/*/data_cache.sqlite; do
    [ -f "$db" ] && python3 -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1],timeout=20); c.execute('delete from storage_v2'); c.commit()" "$db" 2>/dev/null
  done
  logger -t boxy-netwatch "cleared YouTube caches ($1)"
}
if [ -n "$gw" ] && ping -c1 -W3 "$gw" >/dev/null 2>&1; then
  case "$dev" in e*) publish ethernet ;; w*) publish wifi ;; *) publish down ;; esac
  if [ "$(cat "$STATE/fails" 2>/dev/null || echo 0)" != 0 ]; then
    logger -t boxy-netwatch "network is back"; clear_youtube_cache "network back"
  elif [ ! -e "$STATE/booted" ]; then
    clear_youtube_cache "first check after boot"
  fi
  touch "$STATE/booted"; echo 0 > "$STATE/fails"; exit 0
fi
publish down

n=$(( $(cat "$STATE/fails" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$STATE/fails"
logger -t boxy-netwatch "gateway unreachable (check $n)"
conn=$(nmcli -t -f NAME,TYPE con show 2>/dev/null | awk -F: '$2 ~ /wireless/ {print $1; exit}')
case "$n" in
  9)  logger -t boxy-netwatch "toggling Wi-Fi + reconnecting '$conn'"
      nmcli radio wifi off; sleep 2; nmcli radio wifi on; sleep 8
      [ -n "$conn" ] && nmcli con up id "$conn" ;;
  18) logger -t boxy-netwatch "restarting NetworkManager"
      systemctl restart NetworkManager; sleep 10
      [ -n "$conn" ] && nmcli con up id "$conn" ;;
  36) now=$(date +%s); last=$(cat "$LASTREBOOT" 2>/dev/null || echo 0)
      if [ $((now - last)) -gt 21600 ]; then
        echo "$now" > "$LASTREBOOT"; logger -t boxy-netwatch "still offline: rebooting"; systemctl reboot
      fi ;;
esac
