#!/usr/bin/env python3
"""Build Kodi's IPTV playlist from Dispatcharr's, with per-channel source overrides.

Some channels (La7) break inside Dispatcharr's ffmpeg remux at ad breaks (audio ends up
tens of seconds behind video, Kodi drops it). Kodi plays their HLS source fine directly,
so those channels point straight at the source; everything else stays on Dispatcharr.

Overrides: /etc/boxy/iptv-overrides.conf, one "tvg-name|URL" per line (# comments).
Output:    ~barbara/.kodi/userdata/addon_data/pvr.iptvsimple/boxy.m3u (atomic replace;
           left untouched if Dispatcharr can't be reached).
"""
import os, sys, tempfile, urllib.request

SRC = os.environ.get("BOXY_IPTV_M3U", "https://dispatch.barbarhub.com/output/m3u")
CONF = "/etc/boxy/iptv-overrides.conf"
OUT = "/home/barbara/.kodi/userdata/addon_data/pvr.iptvsimple/boxy.m3u"


def overrides():
    o = {}
    try:
        for line in open(CONF, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "|" in line:
                name, url = line.split("|", 1)
                o[name.strip()] = url.strip()
    except FileNotFoundError:
        pass
    return o


def main():
    try:
        data = urllib.request.urlopen(SRC, timeout=30).read().decode("utf-8")
    except Exception as exc:
        print(f"boxy-iptv-m3u: cannot fetch {SRC}: {exc} - keeping existing playlist", file=sys.stderr)
        return 0
    if not data.startswith("#EXTM3U"):
        print("boxy-iptv-m3u: unexpected playlist content - keeping existing playlist", file=sys.stderr)
        return 0
    ov = overrides()
    lines = data.splitlines()
    out, pending, hits = [], None, []
    for line in lines:
        if line.startswith("#EXTINF"):
            pending = None
            for name, url in ov.items():
                if f'tvg-name="{name}"' in line:
                    pending = (name, url)
            out.append(line)
        elif pending and line and not line.startswith("#"):
            # direct HLS sources: let inputstream.adaptive play them (it copes with the
            # server-side ad segments that Kodi's built-in ffmpeg demuxer rejects)
            out.append("#KODIPROP:inputstream=inputstream.adaptive")
            out.append("#KODIPROP:mimetype=application/vnd.apple.mpegurl")
            out.append(pending[1]); hits.append(pending[0]); pending = None
        else:
            out.append(line)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT), prefix=".boxy-m3u-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    os.chmod(tmp, 0o644)
    try:
        os.chown(tmp, 1000, 1000)
    except PermissionError:
        pass
    os.replace(tmp, OUT)
    print(f"boxy-iptv-m3u: {sum(1 for l in out if l.startswith('#EXTINF'))} channels, overridden: {', '.join(hits) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
