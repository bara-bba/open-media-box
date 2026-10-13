"""boxy: stale-while-revalidate snapshots of Spotify directory listings.

A browse_* listing is recorded the first time it is built.  Later requests are answered from the
snapshot straight away (no network, no auth), and a background run of the same URL
(boxy_refresh=1) rebuilds the listing silently and only swaps the snapshot once it is complete.
"""

import hashlib
import json
import os
import sys
import time
import urllib.parse

import xbmc
import xbmcgui
import xbmcplugin
import xbmcvfs

from utils import ADDON_ID, log_msg

SNAP_DIR = xbmcvfs.translatePath(f"special://profile/addon_data/{ADDON_ID}/boxy_snapshots/")
MIN_REFRESH_AGE = 600  # seconds a snapshot is trusted before a background refresh is started
LOCK_TTL = 180
REFRESH_FLAG = "boxy_refresh=1"

_rec = None


class _Recorder:
    def __init__(self, key: str, silent: bool):
        self.key = key
        self.silent = silent
        self.ops = []
        self.items = 0
        self.done = False


def _path(key: str, suffix: str = ".json") -> str:
    return os.path.join(SNAP_DIR, hashlib.md5(key.encode()).hexdigest() + suffix)


def _key(argv2: str) -> str:
    return argv2.replace("&" + REFRESH_FLAG, "").replace(REFRESH_FLAG, "")


class RecListItem(xbmcgui.ListItem):
    _RECORDED = (
        "setInfo",
        "setArt",
        "setProperty",
        "setLabel2",
        "addContextMenuItems",
        "setContentLookup",
        "setMimeType",
    )

    def __init__(self, label="", label2="", path="", offscreen=False):
        super().__init__(label, label2, path, offscreen)
        self._boxy_init = [label, label2, path]
        self._boxy_ops = []

    def _rec(self, name, *args):
        self._boxy_ops.append([name, list(args)])

    def setInfo(self, type, infoLabels):
        self._rec("setInfo", type, infoLabels)
        return super().setInfo(type, infoLabels)

    def setArt(self, dictionary):
        self._rec("setArt", dictionary)
        return super().setArt(dictionary)

    def setProperty(self, key, value):
        self._rec("setProperty", key, value)
        return super().setProperty(key, value)

    def setLabel2(self, label):
        self._rec("setLabel2", label)
        return super().setLabel2(label)

    def addContextMenuItems(self, items, replaceItems=False):
        self._rec("addContextMenuItems", [list(i) for i in items], replaceItems)
        return super().addContextMenuItems(items, replaceItems)

    def setContentLookup(self, enable):
        self._rec("setContentLookup", enable)
        return super().setContentLookup(enable)

    def setMimeType(self, mimetype):
        self._rec("setMimeType", mimetype)
        return super().setMimeType(mimetype)


class _GuiShim:
    ListItem = RecListItem

    def __getattr__(self, name):
        return getattr(xbmcgui, name)


def _record_item(url, li, is_folder, total):
    if _rec is None or _rec.done:
        return
    init = getattr(li, "_boxy_init", None)
    if init is None:
        return
    _rec.ops.append(["item", url, init, li._boxy_ops, bool(is_folder)])
    _rec.items += 1


class _PluginShim:
    def __getattr__(self, name):
        return getattr(xbmcplugin, name)

    def _passthrough(self) -> bool:
        return _rec is not None and _rec.silent

    def _note(self, *op):
        if _rec is not None and not _rec.done:
            _rec.ops.append(list(op))

    def setContent(self, handle, content):
        self._note("setContent", content)
        if not self._passthrough():
            xbmcplugin.setContent(handle, content)

    def setProperty(self, handle, key, value):
        self._note("setProperty", key, value)
        if not self._passthrough():
            xbmcplugin.setProperty(handle, key, value)

    def setPluginCategory(self, handle, category):
        self._note("setPluginCategory", category)
        if not self._passthrough():
            xbmcplugin.setPluginCategory(handle, category)

    def addSortMethod(self, handle, sortMethod, label2Mask=""):
        self._note("addSortMethod", sortMethod)
        if not self._passthrough():
            xbmcplugin.addSortMethod(handle, sortMethod, label2Mask)

    def addDirectoryItem(self, handle, url, listitem, isFolder=False, totalItems=0):
        _record_item(url, listitem, isFolder, totalItems)
        if self._passthrough():
            return True
        return xbmcplugin.addDirectoryItem(handle, url, listitem, isFolder, totalItems)

    def addDirectoryItems(self, handle, items, totalItems=0):
        for url, li, is_folder in items:
            _record_item(url, li, is_folder, totalItems)
        if self._passthrough():
            return True
        return xbmcplugin.addDirectoryItems(handle, items, totalItems)

    def endOfDirectory(self, handle, succeeded=True, updateListing=False, cacheToDisc=True):
        global _rec
        rec = _rec
        if rec is not None and not rec.done:
            rec.done = True
            if succeeded and rec.items:
                _store(rec)
            _release_lock(rec.key)
        if rec is not None and rec.silent:
            return
        xbmcplugin.endOfDirectory(handle, succeeded, updateListing, cacheToDisc)


gui = _GuiShim()
plugin = _PluginShim()


def _store(rec: _Recorder) -> None:
    try:
        os.makedirs(SNAP_DIR, exist_ok=True)
        path = _path(rec.key)
        new = json.dumps(rec.ops, sort_keys=True)
        old = None
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                old = json.dumps(json.load(f).get("ops"), sort_keys=True)
        if old == new:
            os.utime(path, None)
            log_msg(f"Snapshot unchanged: {rec.key}")
            return
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"key": rec.key, "ops": rec.ops}, f)
        os.replace(tmp, path)
        log_msg(f"Snapshot {'updated' if old else 'created'} ({rec.items} items): {rec.key}")
    except Exception as exc:  # never break a listing over caching
        log_msg(f"Snapshot store failed: {exc}")


def _release_lock(key: str) -> None:
    try:
        os.remove(_path(key, ".lock"))
    except OSError:
        pass


def _take_lock(key: str) -> bool:
    lock = _path(key, ".lock")
    try:
        if os.path.exists(lock) and time.time() - os.path.getmtime(lock) < LOCK_TTL:
            return False
        os.makedirs(SNAP_DIR, exist_ok=True)
        with open(lock, "w") as f:
            f.write(str(time.time()))
        return True
    except OSError:
        return False


def _replay(snap: dict, handle: int) -> None:
    items = []
    for op in snap["ops"]:
        kind = op[0]
        if kind == "item":
            _, url, init, ops, is_folder = op
            li = xbmcgui.ListItem(init[0], init[1], init[2], True)
            for name, args in ops:
                if name == "addContextMenuItems":
                    args = [[tuple(i) for i in args[0]], args[1]]
                getattr(li, name)(*args)
            items.append((url, li, is_folder))
        elif kind == "setContent":
            xbmcplugin.setContent(handle, op[1])
        elif kind == "setProperty":
            xbmcplugin.setProperty(handle, op[1], op[2])
        elif kind == "setPluginCategory":
            xbmcplugin.setPluginCategory(handle, op[1])
        elif kind == "addSortMethod":
            xbmcplugin.addSortMethod(handle, op[1])
    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.endOfDirectory(handle)


def serve() -> bool:
    """Call first thing on plugin start. True means the request was fully answered from a snapshot."""
    global _rec
    try:
        handle = int(sys.argv[1])
        argv2 = sys.argv[2] if len(sys.argv) > 2 else ""
        params = urllib.parse.parse_qs(argv2[1:])
        action = (params.get("action") or [""])[0].lower()
        if not action:
            return False
        if not action.startswith("browse_"):
            # anything that is not a plain listing may change what listings contain
            if action.startswith(("follow", "unfollow", "add_", "remove_", "delete_", "refresh", "save", "unsave")):
                if os.path.isdir(SNAP_DIR):
                    for n in os.listdir(SNAP_DIR):
                        if n.endswith(".json"):
                            os.remove(os.path.join(SNAP_DIR, n))
            return False

        key = _key(argv2)
        if REFRESH_FLAG in argv2:
            _rec = _Recorder(key, silent=True)
            return False

        path = _path(key)
        if handle >= 0 and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                snap = json.load(f)
            _replay(snap, handle)
            if time.time() - os.path.getmtime(path) > MIN_REFRESH_AGE and _take_lock(key):
                xbmc.executebuiltin(f"RunPlugin({sys.argv[0]}{key}&{REFRESH_FLAG})")
            return True
        if handle >= 0:
            _rec = _Recorder(key, silent=False)
        return False
    except SystemExit:
        raise
    except Exception as exc:
        log_msg(f"Snapshot serve failed: {exc}")
        _rec = None
        return False
