#!/bin/bash
# Raspotify -> Kodi now-playing bridge.
#
# librespot runs this on every playback event (--onevent) with metadata in the
# environment. We push it into Kodi Home-window properties so the skin can show
# what Spotify Connect is playing. Read-only: playback is still controlled from
# the phone/Spotify app.
#
# librespot provides: PLAYER_EVENT, TRACK_ID, NAME, ARTISTS, ALBUM, COVERS,
#                     DURATION_MS, POSITION_MS  (varies by event/version)
#
# Properties set on the Home window:
#   SpotifyPlaying  "1" while a track is loaded/playing, empty otherwise
#   SpotifyTitle / SpotifyArtist / SpotifyAlbum / SpotifyArt
setprop() {  # setprop <name> <value>  -> SetProperty(name,value,window)
    kodi-send --action="SetProperty($1,$2,home)" >/dev/null 2>&1
}

clear_all() {
    setprop SpotifyPlaying ""
    setprop SpotifyTitle ""
    setprop SpotifyArtist ""
    setprop SpotifyAlbum ""
    setprop SpotifyArt ""
}

# First cover art URL. librespot passes COVERS as a NEWLINE-separated list
# (largest first), so split on any whitespace and take the first entry —
# passing the whole blob would give Kodi an unusable multi-line "URL".
ART="$(printf '%s' "$COVERS" | tr -s ' \t\r\n' '\n' | head -n1)"

case "$PLAYER_EVENT" in
    playing|track_changed|load|loading|started|preloading|changed)
        [ -n "$NAME" ]    && setprop SpotifyTitle  "$NAME"
        [ -n "$ARTISTS" ] && setprop SpotifyArtist "$ARTISTS"
        [ -n "$ALBUM" ]   && setprop SpotifyAlbum  "$ALBUM"
        [ -n "$ART" ]     && setprop SpotifyArt    "$ART"
        setprop SpotifyPlaying "1"
        ;;
    paused)
        # keep the metadata visible, just mark it not actively playing
        setprop SpotifyPlaying ""
        ;;
    stopped|end_of_track|session_disconnected|sink_inactive)
        clear_all
        ;;
esac

exit 0
