#!/bin/sh
# Paint the boxy splash on the framebuffer as early as possible and detach the
# text console so kernel/systemd text never shows. Kodi then shows the same image.
IMG=/usr/local/share/boxy/splash.jpg
for i in $(seq 1 100); do [ -e /dev/fb0 ] && break; sleep 0.1; done
for v in /sys/class/vtconsole/vtcon*; do
  grep -q "frame buffer" "$v/name" 2>/dev/null && echo 0 > "$v/bind" 2>/dev/null
done
exec ffmpeg -nostdin -loglevel error -i "$IMG" -vf scale=1920:1080 -pix_fmt rgb565le -f fbdev /dev/fb0
