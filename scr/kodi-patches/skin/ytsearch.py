"""boxy: YouTube tab click -> search prompt, results open on top of the hub (Back returns to it)."""
import urllib.parse

import xbmc

kb = xbmc.Keyboard("", "Search YouTube")
kb.doModal()
query = kb.getText().strip() if kb.isConfirmed() else ""
if query:
    q = urllib.parse.quote(query)
    xbmc.executebuiltin(
        f"ActivateWindow(videos,plugin://plugin.video.youtube/search/query/?q={q}&category_label={q},return)"
    )
