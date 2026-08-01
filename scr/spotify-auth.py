#!/usr/bin/env python3
"""
One-time Spotify Web API authorisation for the Kodi bridge.

Produces a long-lived *refresh token* so the bridge can pause playback on this
device when Kodi starts a video (instead of stopping raspotify, which makes the
box vanish from the Spotify device list).

Usage on the Pi:
    python3 spotify-auth.py <CLIENT_ID> <CLIENT_SECRET>

It prints a URL: open it in any browser, log in to Spotify, approve, then paste
the URL you land on back into the terminal. The credentials are written to
/etc/spotify-bridge.conf (root-only, 0600).

Scopes requested (playback control only, no library/profile access):
    user-modify-playback-state  — pause/resume
    user-read-playback-state    — see which device is active
"""
import base64
import json
import os
import sys
import urllib.parse
import urllib.request

REDIRECT = "http://127.0.0.1:8888/callback"
SCOPES = "user-modify-playback-state user-read-playback-state"
CONF = "/etc/spotify-bridge.conf"


def post(url, data, headers):
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(data).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    client_id, client_secret = sys.argv[1], sys.argv[2]

    auth_url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT,
        "scope": SCOPES,
    })
    print("\n1) Open this URL in a browser and approve:\n")
    print(auth_url)
    print("\n2) Your browser will fail to load a 127.0.0.1 page — that is")
    print("   expected. Copy the FULL address bar URL and paste it here.\n")
    landed = input("Pasted URL: ").strip()

    query = urllib.parse.urlparse(landed).query
    code = urllib.parse.parse_qs(query).get("code", [None])[0]
    if not code:
        print("No ?code= found in that URL — did you paste the whole thing?")
        return 1

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    tok = post("https://accounts.spotify.com/api/token",
               {"grant_type": "authorization_code",
                "code": code, "redirect_uri": REDIRECT},
               {"Authorization": "Basic " + basic,
                "Content-Type": "application/x-www-form-urlencoded"})

    refresh = tok.get("refresh_token")
    if not refresh:
        print("No refresh_token returned:", tok)
        return 1

    with open(CONF, "w") as f:
        f.write(f"SPOTIFY_CLIENT_ID={client_id}\n")
        f.write(f"SPOTIFY_CLIENT_SECRET={client_secret}\n")
        f.write(f"SPOTIFY_REFRESH_TOKEN={refresh}\n")
    os.chmod(CONF, 0o600)
    print(f"\nSaved to {CONF} (root-only).")
    print("Restart the bridge:  sudo systemctl restart kodi-siri-bridge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
