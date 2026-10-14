"""
freeform_mcp_server.py  (v8 — background engine, no screen stealing)
====================================================================
macOS only. Python 3.10+ (PyObjC + Pillow + numpy).

v8 STRATEGY — everything runs in the background:
  * Freeform is NEVER activated and NEVER brought to the front.
    The user's frontmost app (Chrome, terminal, ...) stays frontmost.
  * Input events are delivered directly to the Freeform process via
    CGEventPostToPid with an NSEvent "primer" pulse, window-number
    stamping (fields 51/98/91/92) and the Command-flag bypass required
    for an inactive target. This recipe was validated end-to-end.
  * Screenshots use `screencapture -x -o -l<WID>` (window-id capture,
    no shadow, no activation) and are normalised to the main window
    bounds even when attached child palettes widen the capture.
  * Objects ALWAYS paste at the viewport centre. Placement therefore
    works as: paste -> measure the new object's centre from a frame
    diff -> nudge with arrow keys (Shift = 10px chunks) -> re-measure
    -> correct. Max 4 iterations, 4px tolerance.
  * Menus are driven through System Events AX (works while backgrounded
    after the primer pulse). Turkish menu labels are used.
  * Drag and scroll-wheel panning are NOT possible for a background
    target (verified) — positioning relies purely on arrow nudging.

COORDINATES:
  All tools take (x, y) offsets in *capture pixels* (2x retina) from
  the viewport centre: x > 0 = right, y > 0 = down.

REMOVED vs v7:
  Click-first placement, calibration offsets, activation round-trips, and
  shape/connector/freehand drawing (they need real drags).
"""

import base64
import functools
import io
import os
import subprocess
import threading
import time
import uuid
import shutil
from pathlib import Path

import numpy as np
import Quartz
from mcp.server.fastmcp import FastMCP
from PIL import Image, ImageChops

try:
    import AppKit  # NSEvent primer
except Exception:  # pragma: no cover
    AppKit = None

try:
    import objc
    from Foundation import NSData, NSDictionary
    objc.loadBundle("Vision", globals(), bundle_path="/System/Library/Frameworks/Vision.framework")
    VNRecognizeTextRequest = objc.lookUpClass("VNRecognizeTextRequest")
    VNImageRequestHandler = objc.lookUpClass("VNImageRequestHandler")
except Exception:  # pragma: no cover
    VNRecognizeTextRequest = None
    VNImageRequestHandler = None

mcp = FastMCP("Freeform MCP")

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------
CMD = Quartz.kCGEventFlagMaskCommand
SHIFT = Quartz.kCGEventFlagMaskShift
F_PID = Quartz.kCGEventTargetUnixProcessID
W_UNDER = getattr(Quartz, "kCGMouseEventWindowUnderMousePointer", 91)
W_UNDER2 = getattr(
    Quartz, "kCGMouseEventWindowUnderMousePointerThatCanHandleThisEvent", 92
)

# macOS virtual key codes
KEY = {
    "return": 36, "tab": 48, "space": 39, "delete": 51, "escape": 53,
    "left": 123, "right": 124, "down": 125, "up": 126,
    "a": 0, "c": 8, "d": 2, "f": 3, "g": 5, "h": 4, "i": 34, "j": 38,
    "k": 40, "l": 37, "m": 46, "n": 45, "o": 31, "p": 35, "q": 12,
    "r": 15, "s": 1, "t": 16, "u": 32, "v": 9, "w": 13, "x": 7,
    "y": 17, "z": 6, "b": 11, "e": 14,
}

# Region of interest inside a window capture: excludes title/toolbar,
# zoom controls and scrollbars. Ratios keep it valid when the board window
# is resized; the original calibrated 2484×1366 values are preserved.
ROI_RATIO = (170 / 1366, 1235 / 1366, 380 / 2484, 2450 / 2484)

# Tolerances (capture px, 2x retina => 4px = 2 logical pt)
PLACE_TOL = 4
PLACE_MAX_ITER = 4
# Measured at 100% zoom: Shift+arrow = 20 capture px (2x retina),
# plain arrow = 2 capture px. Batch key posting drops nothing (verified
# with gap=0.02). Keep the board at 100% zoom while placing objects.
NUDGE_SHIFT_STEP = 20
NUDGE_FINE_STEP = 2
MEASUREMENT_UNCERTAINTY_PX = 0.5
WAIT_INTERVAL_SECONDS = 0.08
WAIT_TIMEOUT_SECONDS = 2.0

# Dragging is empirically unsupported when Freeform remains backgrounded.
# It is deliberately opt-in so it cannot silently replace the verified nudge
# path. Enabling it is for controlled diagnostics only, not production use.
EXPERIMENTAL_BACKGROUND_DRAG = os.getenv("FREEFORM_EXPERIMENTAL_DRAG") == "1"

_state = {"pid": None, "wid": None, "bounds": None, "exp": None}
_operation_lock = threading.RLock()


# ------------------------------------------------------------------
# Low-level helpers
# ------------------------------------------------------------------

def _osascript(script: str):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.stdout.strip(), r.stderr.strip(), r.returncode


def _content_roi(im: Image.Image):
    """Return the dynamic capture ROI as (y0, y1, x0, x1)."""
    height, width = im.height, im.width
    y0_ratio, y1_ratio, x0_ratio, x1_ratio = ROI_RATIO
    y0, y1 = round(height * y0_ratio), round(height * y1_ratio)
    x0, x1 = round(width * x0_ratio), round(width * x1_ratio)
    if y1 <= y0 or x1 <= x0:
        raise RuntimeError(f"invalid content ROI for capture {im.size}")
    return y0, y1, x0, x1


def _wait_for_change(before: Image.Image, timeout: float = WAIT_TIMEOUT_SECONDS):
    """Poll a bounded number of window captures until visible content changes."""
    deadline = time.monotonic() + timeout
    latest = before
    while True:
        latest = _raw_capture()
        if _diff_center(before, latest)[0] is not None:
            return latest, True
        if time.monotonic() >= deadline:
            return latest, False
        time.sleep(WAIT_INTERVAL_SECONDS)


def _serialized_tool(fn):
    """Serialize board access and add a uniform, auditable result envelope."""
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        operation_id = uuid.uuid4().hex
        started = time.monotonic()
        with _operation_lock:
            frontmost_before = _frontmost()
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                result = {"status": "error", "message": str(exc), "verified": False}
            if not isinstance(result, dict):
                result = {"status": "ok", "result": result}
            result.setdefault("status", "ok")
            result["operation_id"] = operation_id
            result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
            result["frontmost_before"] = frontmost_before
            result["frontmost_after"] = _frontmost()
            if "error_px" in result:
                result.setdefault("measurement_uncertainty_px", MEASUREMENT_UNCERTAINTY_PX)
                result.setdefault(
                    "logical_position_verified",
                    max(abs(value) for value in result["error_px"])
                    <= MEASUREMENT_UNCERTAINTY_PX,
                )
            return result
    return wrapped


def _target(refresh: bool = False):
    """Resolve (pid, wid, bounds, exp_size) of the largest board window."""
    if _state["pid"] and _state["wid"] and not refresh:
        return _state["pid"], _state["wid"], _state["bounds"], _state["exp"]

    out = subprocess.run(["pgrep", "-x", "Freeform"], capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout.split():
        raise RuntimeError("Freeform process not running")
    pid = int(out.stdout.split()[0])

    best = None
    for w in Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID
    ):
        if w.get("kCGWindowOwnerName") != "Freeform" or w.get("kCGWindowLayer") != 0:
            continue
        b = w["kCGWindowBounds"]
        if b["Width"] > 500 and b["Height"] > 400:
            area = b["Width"] * b["Height"]
            if best is None or area > best[0]:
                best = (area, w["kCGWindowNumber"], b)
    if best is None:
        raise RuntimeError("No Freeform board window found (Width>500 & Height>400)")

    _, wid, b = best
    exp = (int(b["Width"]) * 2, int(b["Height"]) * 2)
    _state.update(pid=pid, wid=wid, bounds=b, exp=exp)
    return pid, wid, b, exp


def _SIF(ev, field, value):
    Quartz.CGEventSetIntegerValueField(ev, field, value)


def _primer():
    """NSEvent(appKitDefined, subtype 1, WID) -> CGEvent, stamped and
    posted to Freeform. Wakes background event handling; required before
    AX menu clicks and refreshes input routing. Never activates the app."""
    pid, wid, _, _ = _target()
    if AppKit is None:
        raise RuntimeError("PyObjC AppKit unavailable")
    ev = AppKit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
        13, (0, 0), 0, 0.0, wid, None, 1, 0, 0
    )
    cg = ev.CGEvent()
    _SIF(cg, F_PID, pid)
    _SIF(cg, 51, wid)
    _SIF(cg, 58, 1)
    Quartz.CGEventPostToPid(pid, cg)
    time.sleep(0.3)


def _key(kc: int, flags: int = 0, count: int = 1, gap: float = 0.03, tail: float = 0.12):
    """Send `count` key presses (down+up) directly to Freeform."""
    pid, wid, _, _ = _target()
    for _ in range(max(1, count)):
        for down in (True, False):
            ev = Quartz.CGEventCreateKeyboardEvent(None, kc, down)
            _SIF(ev, F_PID, pid)
            _SIF(ev, 51, wid)
            _SIF(ev, 58, 1)
            Quartz.CGEventSetFlags(ev, flags)
            Quartz.CGEventPostToPid(pid, ev)
            time.sleep(0.012)
        time.sleep(gap)
    time.sleep(tail)


def _mouse(typ, x, y, flags=CMD, click_state=None, pressure=None):
    pid, wid, _, _ = _target()
    ev = Quartz.CGEventCreateMouseEvent(None, typ, (x, y), Quartz.kCGMouseButtonLeft)
    _SIF(ev, F_PID, pid)
    _SIF(ev, W_UNDER, wid)
    _SIF(ev, W_UNDER2, wid)
    _SIF(ev, 51, wid)
    _SIF(ev, 58, 1)
    if click_state is not None:
        _SIF(ev, Quartz.kCGMouseEventClickState, click_state)
        if pressure is not None:
            Quartz.CGEventSetDoubleValueField(
                ev, Quartz.kCGMouseEventPressure, pressure
            )
    Quartz.CGEventSetFlags(ev, flags)
    Quartz.CGEventPostToPid(pid, ev)
    time.sleep(0.045)


def _click_screen(sx: float, sy: float, flags=CMD, double: bool = False):
    _mouse(Quartz.kCGEventMouseMoved, sx, sy, flags)
    time.sleep(0.05)
    rounds = 2 if double else 1
    for i in range(rounds):
        cs = i + 1
        _mouse(Quartz.kCGEventLeftMouseDown, sx, sy, flags, cs, 1.0)
        time.sleep(0.10)
        _mouse(Quartz.kCGEventLeftMouseUp, sx, sy, flags, cs, 0.0)
        time.sleep(0.10 if double else 0.25)


def _click_canvas(dx: int, dy: int, double: bool = False):
    """Click at viewport-centre-relative capture px."""
    _, _, b, exp = _target()
    cx = b["X"] + (exp[0] / 2 + dx) / 2
    cy = b["Y"] + (exp[1] / 2 + dy) / 2
    _click_screen(cx, cy, double=double)


def _clip_text(text: str):
    safe = text.replace("\\", "\\\\").replace('"', '\\"')
    _osascript(f'set the clipboard to "{safe}"')
    time.sleep(0.35)


def _clip_png(path: str):
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(str(p))
    _osascript(
        f'set the clipboard to (read (POSIX file "{p}") as «class PNGf»)'
    )
    time.sleep(0.5)


def _type_text(text: str, gap: float = 0.025):
    """Type Unicode into the currently active Freeform text editor.

    Cmd+V is handled as a canvas paste by a background Freeform process,
    even after a sticky note is double-clicked. Unicode keyboard events go
    to the note's editor correctly and keep the label attached to the note.
    """
    pid, wid, _, _ = _target()
    _primer()
    for char in text:
        utf16_units = len(char.encode("utf-16-le")) // 2
        for down in (True, False):
            ev = Quartz.CGEventCreateKeyboardEvent(None, 0, down)
            _SIF(ev, F_PID, pid)
            _SIF(ev, 51, wid)
            _SIF(ev, 58, 1)
            Quartz.CGEventKeyboardSetUnicodeString(ev, utf16_units, char)
            Quartz.CGEventPostToPid(pid, ev)
            time.sleep(gap)


# ------------------------------------------------------------------
# Capture
# ------------------------------------------------------------------

def _raw_capture() -> Image.Image:
    """Capture the board without activating Freeform.

    Quartz window capture is normally sub-second. The `screencapture` fallback
    remains for systems where Quartz does not return a usable image, but it is
    materially slower on some macOS releases.
    """
    pid, wid, b, exp = _target(refresh=True)
    if AppKit is not None:
        try:
            cg_image = Quartz.CGWindowListCreateImage(
                Quartz.CGRectNull,
                Quartz.kCGWindowListOptionIncludingWindow,
                wid,
                Quartz.kCGWindowImageBoundsIgnoreFraming
                | Quartz.kCGWindowImageBestResolution,
            )
            if cg_image is not None:
                bitmap = AppKit.NSBitmapImageRep.alloc().initWithCGImage_(cg_image)
                data = bitmap.representationUsingType_properties_(AppKit.NSPNGFileType, {})
                im = Image.open(io.BytesIO(bytes(data))).convert("RGB")
                if im.size == exp:
                    return im
        except Exception:
            # Fall back below; the existing crop guard remains authoritative.
            pass

    tmp = f"/tmp/_ff_cap_{os.getpid()}.png"
    for _ in range(4):
        subprocess.run(
            ["screencapture", "-x", "-o", "-l", str(wid), tmp],
            capture_output=True,
        )
        if os.path.exists(tmp) and os.path.getsize(tmp) > 1000:
            break
        time.sleep(0.4)
    im = Image.open(tmp).convert("RGB")
    try:
        os.unlink(tmp)
    except OSError:
        pass

    if im.size != exp:
        # Attached child palettes widen the capture; recompute the union
        # of the main window and every layer-0 window intersecting it.
        gx, gy, gw, gh = b["X"], b["Y"], b["Width"], b["Height"]
        minx, miny, maxx, maxy = gx, gy, gx + gw, gy + gh
        for w in Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID
        ):
            if (
                w.get("kCGWindowOwnerName") == "Freeform"
                and w.get("kCGWindowLayer") == 0
                and w["kCGWindowNumber"] != wid
            ):
                wb = w["kCGWindowBounds"]
                if (
                    wb["X"] < maxx
                    and wb["X"] + wb["Width"] > minx
                    and wb["Y"] < maxy
                    and wb["Y"] + wb["Height"] > miny
                ):
                    minx = min(minx, wb["X"])
                    miny = min(miny, wb["Y"])
                    maxx = max(maxx, wb["X"] + wb["Width"])
                    maxy = max(maxy, wb["Y"] + wb["Height"])
        ox, oy = int((minx - gx) * 2), int((miny - gy) * 2)
        im = im.crop((ox, oy, ox + exp[0], oy + exp[1]))
        if im.size != exp:
            raise RuntimeError(f"SIZE_MISMATCH capture={im.size} expected={exp}")
    return im


def _diff_center(before: Image.Image, after: Image.Image):
    """Centre (cx, cy) and bbox of meaningful canvas changes.

    Freeform updates its toolbar and selection affordances during paste and
    nudge. Those changes can span the whole window and used to make a newly
    pasted object's measured centre wildly incorrect. Restrict the comparison
    to the dynamic canvas ROI, then translate the result back to capture
    coordinates.
    """
    if before.size != after.size:
        raise RuntimeError("SIZE_MISMATCH during diff")
    y0, y1, x0, x1 = _content_roi(before)
    d = ImageChops.difference(
        before.crop((x0, y0, x1, y1)), after.crop((x0, y0, x1, y1))
    )
    # Ignore mild compression noise: require a clear per-pixel delta.
    arr = np.asarray(d).astype(np.int16).sum(axis=2)
    mask = arr > 40
    if not mask.any():
        return None, None
    ys, xs = np.where(mask)
    bb = (
        int(xs.min() + x0), int(ys.min() + y0),
        int(xs.max() + x0), int(ys.max() + y0),
    )
    cx = (bb[0] + bb[2]) / 2
    cy = (bb[1] + bb[3]) / 2
    return (cx, cy), bb


def _sticky_center(im: Image.Image):
    """Return the centre of Freeform's default yellow sticky note.

    A note is much larger than its label.  A frame-diff therefore includes
    both old and new overlapping pixels while it moves, which makes the
    difference bounding box unsuitable for placement.  Newly inserted
    Freeform notes use a stable yellow fill, so measure that fill directly.
    """
    arr = np.asarray(im.convert("RGB"))
    mask = (
        (arr[:, :, 0] > 240)
        & (arr[:, :, 1] > 180)
        & (arr[:, :, 1] < 250)
        & (arr[:, :, 2] < 160)
    )
    # Exclude the toolbar and the left zoom controls, which can contain
    # similarly coloured controls/icons.
    y0, _, x0, _ = _content_roi(im)
    mask[:y0, :] = False
    mask[:, :x0] = False
    ys, xs = np.where(mask)
    if len(xs) < 10_000:
        return None
    return ((xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2)


def _nudge(dx: int, dy: int):
    """Move the selected object by (dx, dy) capture px using arrows.

    At 100% zoom Shift+arrow = 20 cap px, plain arrow = 2 cap px.
    """
    _primer()
    for delta, positive_key, negative_key in (
        (dx, KEY["right"], KEY["left"]),
        (dy, KEY["down"], KEY["up"]),
    ):
        if delta == 0:
            continue
        kc = positive_key if delta > 0 else negative_key
        n = abs(int(delta))
        chunks, rest = divmod(n, NUDGE_SHIFT_STEP)
        if chunks:
            _key(kc, flags=SHIFT, count=chunks, gap=0.02, tail=0.05)
        fine = rest // NUDGE_FINE_STEP
        if fine:
            _key(kc, flags=0, count=fine, gap=0.02, tail=0.15)
        elif rest:
            _key(kc, flags=0, count=1, gap=0.02, tail=0.15)


def _clear_board():
    """Esc + Cmd+A + Delete: empties the board (validated)."""
    _primer()
    _click_canvas(0, 0)
    _key(KEY["escape"])
    _key(KEY["a"], flags=CMD)
    _key(KEY["delete"], tail=0.4)
    _key(KEY["escape"], tail=0.2)


def _place_at(target_dx: int, target_dy: int):
    """Paste current clipboard, measure where it landed, nudge it to
    (target_dx, target_dy) relative to the viewport centre.

    Returns dict with measured/achieved offset and iterations, or
    raises if the object cannot be measured at all.
    """
    # CRITICAL: never click before pasting — clicking a text object
    # enters edit mode and Cmd+V then REPLACES that object. Esc twice
    # (leave edit mode + deselect) gives a clean paste target instead.
    _primer()
    _key(KEY["escape"], tail=0.12)
    _key(KEY["escape"], tail=0.2)
    before = _raw_capture()
    _key(KEY["v"], flags=CMD, tail=0.1)
    after, pasted = _wait_for_change(before)
    if not pasted:
        # Self-healing retry: wake up canvas focus if board was recently opened
        _primer()
        _click_canvas(0, 0)
        _key(KEY["escape"], tail=0.15)
        before = _raw_capture()
        _key(KEY["v"], flags=CMD, tail=0.15)
        after, pasted = _wait_for_change(before)
        if not pasted:
            raise RuntimeError("paste did not become visible before timeout")
    center, bb = _diff_center(before, after)
    if center is None:
        raise RuntimeError("paste produced no visible change")

    _, _, b, exp = _target()
    ox, oy = exp[0] / 2, exp[1] / 2
    tx, ty = ox + target_dx, oy + target_dy
    iterations = 0
    prev = after
    cur = center

    for _ in range(PLACE_MAX_ITER):
        dx, dy = tx - cur[0], ty - cur[1]
        if abs(dx) <= PLACE_TOL and abs(dy) <= PLACE_TOL:
            break
        iterations += 1
        _nudge(int(round(dx)), int(round(dy)))
        frame, moved_visible = _wait_for_change(prev)
        if not moved_visible:
            break
        # The object moved: the changed region spans old+new position,
        # so its centre is the midpoint. Recover the new centre.
        moved_center, moved_bb = _diff_center(prev, frame)
        if moved_center is None:
            break  # cannot track further; keep last known position
        new_center = (
            2 * moved_center[0] - cur[0],
            2 * moved_center[1] - cur[1],
        )
        # Guard against garbage (e.g. selection handles dominating):
        if abs(new_center[0] - cur[0]) > 4000 or abs(new_center[1] - cur[1]) > 4000:
            break
        prev = frame
        cur = new_center

    err = (cur[0] - tx, cur[1] - ty)
    return {
        "landed_at_center_offset": (
            round(center[0] - ox, 1),
            round(center[1] - oy, 1),
        ),
        "achieved_offset": (round(cur[0] - ox, 1), round(cur[1] - oy, 1)),
        "target_offset": (target_dx, target_dy),
        "error_px": (round(err[0], 1), round(err[1], 1)),
        "iterations": iterations,
        "verified": abs(err[0]) <= PLACE_TOL and abs(err[1]) <= PLACE_TOL,
    }


MENU_MAP = {
    "tr": {
        "export_pdf": ("Dosya", "Panoyu PDF Olarak Dışa Aktar…"),
        "sticky_note": ("Ekle", "Yapışkan Not"),
        "zoom_100": ("Görüntü", "Büyüt/Küçült", "Gerçek Boyut"),
        "zoom_fit": ("Görüntü", "Büyüt/Küçült", "İçerik Sığacak Şekilde Büyüt/Küçült"),
        "align_left": ("Yerleşim", "Hizala", "Sola Hizala"),
        "align_right": ("Yerleşim", "Hizala", "Sağa Hizala"),
        "align_top": ("Yerleşim", "Hizala", "Yukarı Hizala"),
        "align_bottom": ("Yerleşim", "Hizala", "Aşağı Hizala"),
        "center_h": ("Yerleşim", "Hizala", "Yatay Ortala"),
        "center_v": ("Yerleşim", "Hizala", "Dikey Ortala"),
        "bring_front": ("Yerleşim", "En Üne Getir"),
        "send_back": ("Yerleşim", "En Alta Gönder"),
    },
    "en": {
        "export_pdf": ("File", "Export Board as PDF…"),
        "sticky_note": ("Insert", "Sticky Note"),
        "zoom_100": ("View", "Zoom", "Actual Size"),
        "zoom_fit": ("View", "Zoom", "Zoom to Fit Content"),
        "align_left": ("Arrange", "Align Objects", "Left"),
        "align_right": ("Arrange", "Align Objects", "Right"),
        "align_top": ("Arrange", "Align Objects", "Top"),
        "align_bottom": ("Arrange", "Align Objects", "Bottom"),
        "center_h": ("Arrange", "Align Objects", "Center"),
        "center_v": ("Arrange", "Align Objects", "Middle"),
        "bring_front": ("Arrange", "Bring to Front"),
        "send_back": ("Arrange", "Send to Back"),
    },
}

_detected_lang = None


def _get_freeform_lang() -> str:
    global _detected_lang
    if _detected_lang:
        return _detected_lang
    lang = os.getenv("FREEFORM_LOCALE")
    if lang:
        _detected_lang = "tr" if lang.lower().startswith("tr") else "en"
        return _detected_lang
    out, _, rc = _osascript(
        'tell application "System Events" to tell process "Freeform" to get name of menu bar item 3 of menu bar 1'
    )
    if rc == 0 and out.strip() == "Dosya":
        _detected_lang = "tr"
    else:
        _detected_lang = "en"
    return _detected_lang


def _resolve_menu_path(*path_or_key):
    """Resolve semantic menu key or language-specific menu path."""
    if len(path_or_key) == 1 and isinstance(path_or_key[0], str) and path_or_key[0] in MENU_MAP["tr"]:
        lang = _get_freeform_lang()
        resolved = MENU_MAP.get(lang, MENU_MAP["en"]).get(path_or_key[0])
        if resolved:
            return resolved
    return path_or_key


def _ax_menu(*path):
    """Click a Freeform menu path through System Events (background-safe
    after a primer pulse). Supports semantic keys (e.g. 'sticky_note')
    or explicit paths (e.g. ('Ekle', 'Yapışkan Not'))."""
    path = _resolve_menu_path(*path)
    _primer()
    if len(path) == 2:
        menu, item = path
        script = f'''
        tell application "System Events"
          tell process "Freeform"
            click menu item "{item}" of menu 1 of menu bar item "{menu}" of menu bar 1
          end tell
        end tell'''
    elif len(path) == 3:
        menu, sub, leaf = path
        script = f'''
        tell application "System Events"
          tell process "Freeform"
            click menu item "{leaf}" of menu 1 of menu item "{sub}" of menu 1 of menu bar item "{menu}" of menu bar 1
          end tell
        end tell'''
    else:
        return False
    _, err, rc = _osascript(script)
    time.sleep(0.45)
    if rc != 0:
        # Fallback: index-based lookup for submenus.
        if len(path) == 3:
            _, err2, rc2 = _osascript(f'''
            tell application "System Events"
              tell process "Freeform"
                set m to menu 1 of menu bar item "{path[0]}" of menu bar 1
                perform (menu item "{path[2]}" of menu 1 of menu item "{path[1]}" of m)
              end tell
            end tell''')
            time.sleep(0.45)
            return rc2 == 0
        raise RuntimeError(f"menu click failed: {err.strip()}")
    return True


def _frontmost():
    out, _, _ = _osascript(
        'tell application "System Events" to get name of first '
        "application process whose frontmost is true"
    )
    return out


# ------------------------------------------------------------------
# Board management tools
# ------------------------------------------------------------------

@mcp.tool()
@_serialized_tool
def board_new() -> dict:
    """Open Freeform if needed and report the active board window.

    Does NOT steal focus: if Freeform is already running with an open
    board (the normal background case) nothing is activated at all.
    """
    out, _, _ = _osascript(
        'tell application "System Events" to (name of processes) contains "Freeform"'
    )
    if out != "true":
        subprocess.Popen(["open", "-a", "Freeform"])
        time.sleep(4.0)
        _primer()
    try:
        pid, wid, b, exp = _target(refresh=True)
        return {
            "status": "ok",
            "window_id": wid,
            "bounds": {k: b[k] for k in ("X", "Y", "Width", "Height")},
            "capture_size": list(exp),
            "frontmost_unchanged": _frontmost(),
        }
    except RuntimeError as e:
        # No board window: create one (unavoidable single activation).
        _osascript('tell application "Freeform" to make new document')
        time.sleep(2.5)
        pid, wid, b, exp = _target(refresh=True)
        return {
            "status": "ok",
            "created_board": True,
            "window_id": wid,
            "capture_size": list(exp),
        }


@mcp.tool()
@_serialized_tool
def board_open(file_path: str) -> dict:
    """Open an existing .freeform file (single activation is unavoidable)."""
    p = Path(file_path).expanduser()
    if not p.exists():
        return {"status": "error", "message": f"File not found: {file_path}"}
    subprocess.Popen(["open", str(p)])
    time.sleep(3.0)
    _primer()
    _, wid, b, exp = _target(refresh=True)
    return {"status": "ok", "file": p.name, "window_id": wid, "capture_size": list(exp)}


@mcp.tool()
@_serialized_tool
def board_save() -> dict:
    """Save the board (Cmd+S), backgrounded."""
    _primer()
    _key(KEY["s"], flags=CMD, tail=0.7)
    return {"status": "ok", "frontmost": _frontmost()}


@mcp.tool()
@_serialized_tool
def board_undo() -> dict:
    """Undo (Cmd+Z), backgrounded."""
    _primer()
    _key(KEY["z"], flags=CMD, tail=0.4)
    return {"status": "ok"}


@mcp.tool()
@_serialized_tool
def board_redo() -> dict:
    """Redo (Cmd+Shift+Z), backgrounded."""
    _primer()
    _key(KEY["z"], flags=CMD | SHIFT, tail=0.4)
    return {"status": "ok"}


@mcp.tool()
@_serialized_tool
def board_clear() -> dict:
    """Empty the whole board (Esc, Cmd+A, Delete). Validated."""
    before = _raw_capture()
    _clear_board()
    after, changed_visible = _wait_for_change(before)
    center, _ = _diff_center(before, after)
    return {
        "status": "ok",
        "changed": changed_visible and center is not None,
        "frontmost": _frontmost(),
    }


@mcp.tool()
@_serialized_tool
def board_screenshot() -> dict:
    """Frameless window screenshot (no activation). Returns base64 PNG."""
    im = _raw_capture()
    buf = __import__("io").BytesIO()
    im.save(buf, format="PNG")
    return {
        "status": "ok",
        "format": "png",
        "size": list(im.size),
        "image_base64": base64.b64encode(buf.getvalue()).decode(),
    }


def _dismiss_any_sheets():
    """Dismiss any modal save sheets or alerts in Freeform to release keyboard focus."""
    _osascript('''
    tell application "System Events"
      tell process "Freeform"
        repeat with w in windows
          try
            if exists sheet 1 of w then
              try
                click button "Vazgeç" of sheet 1 of w
              end try
              try
                click button "Cancel" of sheet 1 of w
              end try
            end if
          end try
        end repeat
      end tell
    end tell''')
    _key(KEY["escape"], tail=0.1)


@mcp.tool()
@_serialized_tool
def board_export_pdf(output_path: str, dpi: int = 144) -> dict:
    """Export the current board canvas directly as a clean, high-resolution PDF file.

    100% background-safe: NEVER opens macOS Save dialogs and NEVER steals keyboard focus.
    """
    _dismiss_any_sheets()
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    im = _raw_capture()
    y0, y1, x0, x1 = _content_roi(im)
    cropped = im.crop((x0, y0, x1, y1))
    cropped.convert("RGB").save(str(target), "PDF", resolution=float(dpi))

    return {
        "status": "ok",
        "method": "direct_capture_pdf",
        "file": str(target),
        "size_bytes": os.path.getsize(str(target)),
        "resolution_dpi": dpi,
        "frontmost": _frontmost(),
    }


@mcp.tool()
@_serialized_tool
def board_zoom(level: str = "fit") -> dict:
    """Zoom: fit | in | out | 100.

    fit/100 use the View menu (Görüntü > Büyüt/Küçült); in/out click the
    in-window zoom bar buttons (validated while backgrounded).
    """
    _, _, b, exp = _target(refresh=True)
    if level == "out":
        _click_screen(b["X"] + b["Width"] * (29 / 1242), b["Y"] + b["Height"] * (651 / 683))
        time.sleep(0.15)
    elif level == "in":
        _click_screen(b["X"] + b["Width"] * (57 / 1242), b["Y"] + b["Height"] * (651 / 683))
        time.sleep(0.15)
    elif level == "100":
        _ax_menu("zoom_100")
    elif level == "fit":
        _ax_menu("zoom_fit")
    else:
        return {"status": "error", "message": "Use: fit | in | out | 100"}
    return {"status": "ok", "zoom": level}


@mcp.tool()
@_serialized_tool
def debug_info() -> dict:
    """Diagnostics: pid, window id/bounds, capture size, frontmost app."""
    try:
        pid, wid, b, exp = _target(refresh=True)
        im = _raw_capture()
        y0, y1, x0, x1 = _content_roi(im)
        roi = np.asarray(im)[y0:y1, x0:x1]
        dark = int((roi.max(axis=2) < 170).sum())
        return {
            "status": "ok",
            "pid": pid,
            "window_id": wid,
            "bounds": {k: b[k] for k in ("X", "Y", "Width", "Height")},
            "capture_size": list(im.size),
            "content_roi": {"y0": y0, "y1": y1, "x0": x0, "x1": x1},
            "roi_dark_pixels": dark,
            "freeform_language": _get_freeform_lang(),
            "experimental_background_drag": EXPERIMENTAL_BACKGROUND_DRAG,
            "frontmost": _frontmost(),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ------------------------------------------------------------------
# Content tools
# ------------------------------------------------------------------

@mcp.tool()
@_serialized_tool
def text_add(
    text: str, x: int = 0, y: int = 0, bold: bool = False, italic: bool = False
) -> dict:
    """Paste `text` as a text object, then place its centre at (x, y).

    x, y are capture px (2x retina) offsets from the viewport centre.
    The object is measured and arrow-nudged into place automatically.
    """
    _clip_text(text)
    result = _place_at(x, y)
    if bold or italic:
        # Re-select by clicking the placed object, apply style.
        _click_canvas(x, y)
        if bold:
            _key(KEY["b"], flags=CMD, tail=0.25)
        if italic:
            _key(KEY["i"], flags=CMD, tail=0.25)
        _key(KEY["escape"], tail=0.2)
    return {"status": "ok", "text": text, **result}


@mcp.tool()
@_serialized_tool
def image_insert(file_path: str, x: int = 0, y: int = 0) -> dict:
    """Paste an image file as an object centred at (x, y).

    Reads the PNG/JPEG into the clipboard and Cmd+V's it, then nudges
    the object into place. x, y: capture px offsets from viewport centre.
    """
    p = Path(file_path).expanduser()
    if not p.exists():
        return {"status": "error", "message": f"File not found: {file_path}"}
    suffix = p.suffix.lower()
    if suffix in (".png", ".PNG"):
        _clip_png(str(p))
    else:
        # Non-PNG: convert to PNG on the fly (clipboard accepts PNGF).
        tmp = f"/tmp/_ff_clip_{os.getpid()}.png"
        Image.open(p).convert("RGB").save(tmp)
        _clip_png(tmp)
        try:
            os.unlink(tmp)
        except OSError:
            pass
    result = _place_at(x, y)
    return {"status": "ok", "image": p.name, **result}


@mcp.tool()
@_serialized_tool
def shape_svg_insert(
    svg: str,
    x: int = 0,
    y: int = 0,
    width: int = 240,
    height: int = 240,
) -> dict:
    """Insert an SVG shape (raw SVG string or file path) centred at (x, y) capture px.

    Converts SVG to a high-resolution transparent PNG, loads into clipboard,
    pastes at viewport centre, and nudges to target offset.
    """
    tmp_svg = None
    if os.path.exists(os.path.expanduser(svg)):
        svg_path = str(Path(svg).expanduser().resolve())
    else:
        tmp_svg = f"/tmp/_ff_shape_{os.getpid()}_{uuid.uuid4().hex[:6]}.svg"
        with open(tmp_svg, "w", encoding="utf-8") as f:
            f.write(svg)
        svg_path = tmp_svg

    tmp_png = f"/tmp/_ff_shape_{os.getpid()}_{uuid.uuid4().hex[:6]}.png"
    rendered = False

    # 1. Try ImageMagick if available
    magick_path = "/usr/local/bin/magick" if os.path.exists("/usr/local/bin/magick") else "magick"
    try:
        r = subprocess.run(
            [magick_path, "-background", "none", "-density", "300", svg_path, "-resize", f"{width}x{height}", tmp_png],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0 and os.path.exists(tmp_png) and os.path.getsize(tmp_png) > 0:
            rendered = True
    except Exception:
        pass

    # 2. Fallback: QuickLook thumbnail via qlmanage
    if not rendered and os.path.exists("/usr/bin/qlmanage"):
        try:
            out_dir = f"/tmp/_ql_{uuid.uuid4().hex[:6]}"
            os.makedirs(out_dir, exist_ok=True)
            subprocess.run(
                ["/usr/bin/qlmanage", "-t", "-s", str(max(width, height) * 2), "-o", out_dir, svg_path],
                capture_output=True,
                text=True,
            )
            candidates = list(Path(out_dir).glob("*.png"))
            if candidates:
                cand = candidates[0]
                with Image.open(cand) as im:
                    im.resize((width, height), Image.Resampling.LANCZOS).save(tmp_png)
                rendered = True
            shutil.rmtree(out_dir, ignore_errors=True)
        except Exception:
            pass

    if not rendered:
        if tmp_svg and os.path.exists(tmp_svg):
            os.unlink(tmp_svg)
        return {"status": "error", "message": "Failed to render SVG to transparent PNG"}

    _clip_png(tmp_png)
    result = _place_at(x, y)

    try:
        if os.path.exists(tmp_png):
            os.unlink(tmp_png)
        if tmp_svg and os.path.exists(tmp_svg):
            os.unlink(tmp_svg)
    except OSError:
        pass

    return {"status": "ok", "shape": "svg", **result}


@mcp.tool()
@_serialized_tool
def sticky_add(text: str, x: int = 0, y: int = 0) -> dict:
    """Insert a sticky note (Ekle > Yapışkan Not) and place it at (x, y).

    The note is inserted at the viewport centre, typed into (paste), then
    measured and nudged to the target offset.
    """
    # The note editor receives Cmd+V below. Populate the clipboard first;
    # otherwise a prior text/image operation is pasted into the new note.
    before_insert = _raw_capture()
    _ax_menu("sticky_note")
    inserted, inserted_visible = _wait_for_change(before_insert)
    if not inserted_visible:
        raise RuntimeError("sticky note did not become visible before timeout")
    inserted_center = _sticky_center(inserted)
    if inserted_center is None:
        raise RuntimeError("could not measure the inserted yellow sticky note")
    _, _, _, exp = _target()
    ox, oy = exp[0] / 2, exp[1] / 2
    # A new note is selected, not text-editing. Double-clicking its measured
    # centre enters its editor; without this, Cmd+V creates a separate text
    # object beside the note.
    _click_canvas(
        int(round(inserted_center[0] - ox)),
        int(round(inserted_center[1] - oy)),
        double=True,
    )
    _type_text(text)
    _key(KEY["escape"], tail=0.3)  # leave text edit and return to canvas

    after = _raw_capture()
    center = _sticky_center(after)
    if center is None:
        raise RuntimeError("could not measure the inserted yellow sticky note")

    tx, ty = ox + x, oy + y
    cur = center
    iterations = 0
    # Esc exits note editing *and* deselects the note. Re-select at its
    # measured centre before each nudge, then measure the yellow fill in a
    # clean, deselected frame. This avoids frame-diff ambiguity when the
    # large old/new sticky rectangles overlap.
    for _ in range(PLACE_MAX_ITER):
        dx, dy = tx - cur[0], ty - cur[1]
        if abs(dx) <= PLACE_TOL and abs(dy) <= PLACE_TOL:
            break
        iterations += 1
        _click_canvas(int(round(cur[0] - ox)), int(round(cur[1] - oy)))
        _nudge(int(round(dx)), int(round(dy)))
        _key(KEY["escape"], tail=0.3)
        frame, moved_visible = _wait_for_change(after)
        if not moved_visible:
            break
        new = _sticky_center(frame)
        if new is None:
            raise RuntimeError("could not re-measure sticky note after moving it")
        cur, after = new, frame
    err = (cur[0] - tx, cur[1] - ty)
    return {
        "status": "ok",
        "text": text,
        "achieved_offset": (float(round(cur[0] - ox, 1)), float(round(cur[1] - oy, 1))),
        "error_px": (float(round(err[0], 1)), float(round(err[1], 1))),
        "iterations": iterations,
        "verified": bool(abs(err[0]) <= PLACE_TOL and abs(err[1]) <= PLACE_TOL),
    }


# ------------------------------------------------------------------
# Selection / object tools
# ------------------------------------------------------------------

@mcp.tool()
@_serialized_tool
def select_all() -> dict:
    """Select all objects (Cmd+A), backgrounded."""
    _primer()
    _key(KEY["a"], flags=CMD, tail=0.3)
    return {"status": "ok"}


@mcp.tool()
@_serialized_tool
def select_at(x: int, y: int) -> dict:
    """Click-select the object at viewport offset (x, y) capture px."""
    _primer()
    _click_canvas(x, y)
    return {"status": "ok"}


@mcp.tool()
@_serialized_tool
def select_deselect() -> dict:
    """Deselect everything (Esc)."""
    _primer()
    _key(KEY["escape"], tail=0.25)
    return {"status": "ok"}


@mcp.tool()
@_serialized_tool
def object_delete() -> dict:
    """Delete the selected object(s)."""
    _primer()
    _key(KEY["delete"], tail=0.4)
    return {"status": "ok"}


@mcp.tool()
@_serialized_tool
def object_duplicate() -> dict:
    """Duplicate the selection (Cmd+D)."""
    _primer()
    _key(KEY["d"], flags=CMD, tail=0.4)
    return {"status": "ok"}


@mcp.tool()
@_serialized_tool
def object_move(dx: int, dy: int) -> dict:
    """Nudge the selection by (dx, dy) capture px with arrow keys."""
    before = _raw_capture()
    _nudge(dx, dy)
    after, changed_visible = _wait_for_change(before)
    center, bb = _diff_center(before, after)
    return {
        "status": "ok",
        "requested": {"dx": dx, "dy": dy},
        "changed": changed_visible and center is not None,
        "diff_bbox": bb,
    }


@mcp.tool()
@_serialized_tool
def object_drag(dx: int, dy: int) -> dict:
    """Experimental only: attempt a background drag of the current selection.

    Disabled unless FREEFORM_EXPERIMENTAL_DRAG=1 is present when the server
    starts. It is not part of the verified placement path: background drags
    have repeatedly failed to move Freeform objects without activation.
    """
    if not EXPERIMENTAL_BACKGROUND_DRAG:
        return {
            "status": "error",
            "message": "Experimental background drag is disabled; use object_move.",
            "verified": False,
            "experimental": True,
        }
    return {
        "status": "error",
        "message": "Background drag remains diagnostic-only and is not verified.",
        "verified": False,
        "experimental": True,
        "requested": {"dx": dx, "dy": dy},
    }


@mcp.tool()
@_serialized_tool
def object_group() -> dict:
    """Group the selection (Cmd+G)."""
    _primer()
    _key(KEY["g"], flags=CMD, tail=0.35)
    return {"status": "ok"}


@mcp.tool()
@_serialized_tool
def object_ungroup() -> dict:
    """Ungroup the selection (Cmd+Shift+G)."""
    _primer()
    _key(KEY["g"], flags=CMD | SHIFT, tail=0.35)
    return {"status": "ok"}


@mcp.tool()
@_serialized_tool
def arrange(action: str) -> dict:
    """Align/arrange the selection via the Arrange menu (Yerleşim / Arrange).

    Actions: align_left, align_right, align_top, align_bottom,
    center_h, center_v, bring_front, send_back.
    """
    valid_actions = (
        "align_left", "align_right", "align_top", "align_bottom",
        "center_h", "center_v", "bring_front", "send_back",
    )
    if action not in valid_actions:
        return {"status": "error", "message": f"Choose from: {list(valid_actions)}"}
    ok = _ax_menu(action)
    return {"status": "ok" if ok else "error", "action": action}


# ------------------------------------------------------------------
# Advanced Inspection & Batch Layout tools
# ------------------------------------------------------------------

def _scan_canvas_texts(im: Image.Image) -> list[dict]:
    """Extract visible text blocks and canvas-relative coordinates using Apple Vision."""
    if VNRecognizeTextRequest is None or VNImageRequestHandler is None:
        return []

    buf = io.BytesIO()
    im.save(buf, format="PNG")
    data = buf.getvalue()
    ns_data = NSData.dataWithBytes_length_(data, len(data))
    handler = VNImageRequestHandler.alloc().initWithData_options_(ns_data, NSDictionary.dictionary())
    req = VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(1)  # accurate recognition
    req.setUsesLanguageCorrection_(True)
    try:
        req.setRecognitionLanguages_(["tr-TR", "en-US"])
    except Exception:
        pass

    success = handler.performRequests_error_([req], None)
    if not success:
        return []

    w, h = im.size
    ox, oy = w / 2, h / 2
    y0, y1, x0, x1 = _content_roi(im)

    results = []
    for observation in req.results() or []:
        candidates = observation.topCandidates_(1)
        if not candidates:
            continue
        cand = candidates[0]
        text = str(cand.string())
        conf = float(round(cand.confidence(), 3))

        bbox = observation.boundingBox()
        # Vision origin is bottom-left, y up
        px_left = float(round(bbox.origin.x * w, 1))
        px_w = float(round(bbox.size.width * w, 1))
        px_h = float(round(bbox.size.height * h, 1))
        px_top = float(round((1.0 - (bbox.origin.y + bbox.size.height)) * h, 1))

        cx_px = px_left + px_w / 2
        cy_px = px_top + px_h / 2

        # Filter out text outside content ROI (toolbar, window title, zoom controls)
        if not (x0 <= cx_px <= x1 and y0 <= cy_px <= y1):
            continue

        rel_x = float(round(cx_px - ox, 1))
        rel_y = float(round(cy_px - oy, 1))

        results.append({
            "text": text,
            "confidence": conf,
            "center_offset": {"x": rel_x, "y": rel_y},
            "box": {
                "left": px_left,
                "top": px_top,
                "width": px_w,
                "height": px_h,
            },
        })

    return results


@mcp.tool()
@_serialized_tool
def board_scan() -> dict:
    """Scan the board using Apple Vision OCR to discover texts and their (x, y) coordinates.

    Returns recognized text snippets with their relative canvas offsets (x, y)
    from viewport centre, allowing direct interaction via select_at(x, y).
    """
    im = _raw_capture()
    w, h = im.size
    texts = _scan_canvas_texts(im)
    return {
        "status": "ok",
        "capture_size": [w, h],
        "viewport_center": [w / 2, h / 2],
        "total_texts": len(texts),
        "texts": texts,
    }


@mcp.tool()
@_serialized_tool
def board_create_grid(
    items: list[dict],
    cols: int = 5,
    spacing_x: int = 300,
    spacing_y: int = 220,
    start_x: int | None = None,
    start_y: int | None = None,
    caption_offset_y: int = 100,
) -> dict:
    """Batch-place a list of items (images, texts, stickies) in a grid layout.

    Each item in `items` is a dict:
      - For images: {"type": "image", "file_path": "/path/to/img.png", "caption": "Optional title"}
      - For text: {"type": "text", "text": "Content", "bold": False, "italic": False}
      - For stickies: {"type": "sticky", "text": "Note content"}

    If type is omitted, 'image' is inferred if 'file_path' is given, else 'text'.
    If start_x/start_y are omitted, the grid is automatically centred around (0, 0).
    """
    if not items:
        return {"status": "error", "message": "items list is empty"}
    if cols <= 0:
        cols = 1

    n = len(items)
    rows = (n + cols - 1) // cols

    actual_cols = min(n, cols)
    if start_x is None:
        start_x = int(-((actual_cols - 1) * spacing_x) / 2) if actual_cols > 1 else 0
    if start_y is None:
        start_y = int(-((rows - 1) * spacing_y) / 2) if rows > 1 else 0

    results = []
    for i, it in enumerate(items):
        r = i // cols
        c = i % cols
        target_x = int(start_x + c * spacing_x)
        target_y = int(start_y + r * spacing_y)

        item_type = it.get("type")
        if not item_type:
            item_type = "image" if "file_path" in it else "text"

        entry = {
            "index": i,
            "type": item_type,
            "target": {"x": target_x, "y": target_y},
        }

        if item_type == "image":
            fp = it.get("file_path")
            if not fp:
                entry["status"] = "error"
                entry["message"] = "Missing file_path"
                results.append(entry)
                continue
            res = image_insert(fp, x=target_x, y=target_y)
            entry["result"] = res
            caption = it.get("caption") or it.get("text")
            if caption:
                cap_res = text_add(
                    caption,
                    x=target_x,
                    y=target_y + caption_offset_y,
                    bold=it.get("bold", False),
                    italic=it.get("italic", False),
                )
                entry["caption_result"] = cap_res

        elif item_type == "sticky":
            txt = it.get("text", "")
            res = sticky_add(txt, x=target_x, y=target_y)
            entry["result"] = res

        elif item_type == "svg":
            svg_data = it.get("svg") or it.get("svg_data") or it.get("file_path") or ""
            res = shape_svg_insert(
                svg_data,
                x=target_x,
                y=target_y,
                width=it.get("width", 240),
                height=it.get("height", 240),
            )
            entry["result"] = res
            caption = it.get("caption")
            if caption:
                cap_res = text_add(
                    caption,
                    x=target_x,
                    y=target_y + caption_offset_y,
                    bold=it.get("bold", False),
                    italic=it.get("italic", False),
                )
                entry["caption_result"] = cap_res

        elif item_type == "text":
            txt = it.get("text", "")
            res = text_add(
                txt,
                x=target_x,
                y=target_y,
                bold=it.get("bold", False),
                italic=it.get("italic", False),
            )
            entry["result"] = res

        else:
            entry["status"] = "error"
            entry["message"] = f"Unknown item type: {item_type}"

        results.append(entry)

    return {
        "status": "ok",
        "total_items": n,
        "grid": {"cols": cols, "rows": rows, "spacing_x": spacing_x, "spacing_y": spacing_y},
        "items": results,
    }


@mcp.tool()
@_serialized_tool
def board_find_and_select(query: str, select: bool = True) -> dict:
    """Find a text snippet on the board using Vision OCR and optionally click-select it.

    Enables semantic interaction (e.g. 'find the card labeled Git 2 and select it').
    Returns coordinates and match details.
    """
    im = _raw_capture()
    texts = _scan_canvas_texts(im)
    if not texts:
        return {"status": "ok", "found": False, "query": query, "message": "No text detected on canvas"}

    import re

    def _norm(s: str) -> str:
        return re.sub(r'[\s_\-•.,:;]+', '', s.lower())

    q_norm = _norm(query)
    q_lower = query.strip().lower()
    best_match = None
    best_score = -1

    for t in texts:
        raw_txt = t["text"].strip()
        txt = raw_txt.lower()
        t_norm = _norm(raw_txt)
        score = 0
        if txt == q_lower or (t_norm and t_norm == q_norm):
            score = 100
        elif (q_norm and q_norm in t_norm) or (t_norm and t_norm in q_norm) or (q_lower in txt):
            score = 85
        elif any(w in txt for w in q_lower.split() if len(w) > 2):
            score = 60

        if score > best_score:
            best_score = score
            best_match = t

    if not best_match or best_score < 40:
        return {
            "status": "ok",
            "found": False,
            "query": query,
            "total_candidates": len(texts),
            "message": f"Text matching '{query}' not found on board",
        }

    cx = best_match["center_offset"]["x"]
    cy = best_match["center_offset"]["y"]

    if select:
        _primer()
        _click_canvas(int(round(cx)), int(round(cy)))

    return {
        "status": "ok",
        "found": True,
        "query": query,
        "match_score": best_score,
        "matched_text": best_match["text"],
        "confidence": best_match["confidence"],
        "center_offset": {"x": cx, "y": cy},
        "box": best_match["box"],
        "selected": select,
    }


def _generate_preset_svg(
    preset: str,
    color: str = "#2196F3",
    label: str = "",
    width: int = 240,
    height: int = 120,
) -> str:
    """Generate parametric SVG markup for standard diagram components."""
    font_family = "system-ui, -apple-system, sans-serif"
    label_esc = label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    label_xml = (
        f'<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" '
        f'fill="#FFFFFF" font-family="{font_family}" font-size="16" font-weight="bold">{label_esc}</text>'
        if label
        else ""
    )

    if preset == "arrow_right":
        return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 80" width="{width}" height="{height}">
          <path d="M20 30 L130 30 L130 10 L185 40 L130 70 L130 50 L20 50 Z" fill="{color}"/>
          {label_xml}
        </svg>'''
    elif preset == "arrow_left":
        return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 80" width="{width}" height="{height}">
          <path d="M180 30 L70 30 L70 10 L15 40 L70 70 L70 50 L180 50 Z" fill="{color}"/>
          {label_xml}
        </svg>'''
    elif preset == "arrow_down":
        return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 200" width="{width}" height="{height}">
          <path d="M30 20 L30 130 L10 130 L40 185 L70 130 L50 130 L50 20 Z" fill="{color}"/>
          {label_xml}
        </svg>'''
    elif preset == "arrow_up":
        return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 200" width="{width}" height="{height}">
          <path d="M30 180 L30 70 L10 70 L40 15 L70 70 L50 70 L50 180 Z" fill="{color}"/>
          {label_xml}
        </svg>'''
    elif preset == "rounded_card":
        return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 120" width="{width}" height="{height}">
          <rect x="4" y="4" width="232" height="112" rx="16" ry="16" fill="{color}" stroke="#000000" stroke-opacity="0.1" stroke-width="3"/>
          {label_xml}
        </svg>'''
    elif preset == "database":
        return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 200" width="{width}" height="{height}">
          <path d="M20 40 C20 20, 140 20, 140 40 L140 160 C140 180, 20 180, 20 160 Z" fill="{color}"/>
          <ellipse cx="80" cy="40" rx="60" ry="22" fill="#FFFFFF" fill-opacity="0.25"/>
          <ellipse cx="80" cy="100" rx="60" ry="20" fill="none" stroke="#FFFFFF" stroke-opacity="0.3" stroke-width="4"/>
          <ellipse cx="80" cy="160" rx="60" ry="20" fill="none" stroke="#FFFFFF" stroke-opacity="0.3" stroke-width="4"/>
          {label_xml}
        </svg>'''
    elif preset == "cloud":
        return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 160" width="{width}" height="{height}">
          <path d="M60 130 L190 130 C215 130, 230 110, 220 85 C220 60, 195 55, 180 60 C165 30, 120 30, 105 55 C95 45, 75 45, 65 60 C40 60, 30 80, 35 105 C25 125, 45 130, 60 130 Z" fill="{color}"/>
          {label_xml}
        </svg>'''
    elif preset == "decision_diamond":
        return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="{width}" height="{height}">
          <polygon points="100,10 190,100 100,190 10,100" fill="{color}"/>
          {label_xml}
        </svg>'''
    elif preset == "badge_check":
        c = color or "#4CAF50"
        return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="{width}" height="{height}">
          <circle cx="50" cy="50" r="45" fill="{c}"/>
          <path d="M30 50 L45 65 L70 35" fill="none" stroke="#FFFFFF" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>'''
    elif preset == "badge_warning":
        c = color or "#FF9800"
        return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="{width}" height="{height}">
          <polygon points="50,10 90,85 10,85" fill="{c}"/>
          <line x1="50" y1="38" x2="50" y2="60" stroke="#FFFFFF" stroke-width="7" stroke-linecap="round"/>
          <circle cx="50" cy="74" r="5" fill="#FFFFFF"/>
        </svg>'''
    else:
        # Default simple box
        return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100" width="{width}" height="{height}">
          <rect x="5" y="5" width="190" height="90" rx="8" fill="{color}"/>
          {label_xml}
        </svg>'''


@mcp.tool()
@_serialized_tool
def shape_insert_preset(
    preset: str,
    x: int = 0,
    y: int = 0,
    color: str = "#2196F3",
    label: str = "",
    width: int = 240,
    height: int = 120,
) -> dict:
    """Insert a standard parametric diagram component at (x, y) capture px.

    Presets:
      - 'arrow_right', 'arrow_left', 'arrow_down', 'arrow_up'
      - 'rounded_card'
      - 'database'
      - 'cloud'
      - 'decision_diamond'
      - 'badge_check', 'badge_warning'
    """
    svg_code = _generate_preset_svg(preset, color=color, label=label, width=width, height=height)
    res = shape_svg_insert(svg_code, x=x, y=y, width=width, height=height)
    return {
        "status": "ok",
        "preset": preset,
        "label": label,
        "color": color,
        **res,
    }


@mcp.tool()
@_serialized_tool
def board_export_pack(output_dir: str) -> dict:
    """Export the current board package: high-resolution PDF, PNG, and JSON metadata.

    Saves into `output_dir`:
      - board.pdf (PDF vector/raster export)
      - board.png (Full frameless canvas screenshot)
      - board_metadata.json (Vision OCR dump with all texts and coordinates)
    """
    dest = Path(output_dir).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)

    pdf_file = dest / "board.pdf"
    png_file = dest / "board.png"
    json_file = dest / "board_metadata.json"

    # 1. Export PDF
    pdf_res = board_export_pdf(str(pdf_file))

    # 2. Screenshot PNG
    im = _raw_capture()
    y0, y1, x0, x1 = _content_roi(im)
    cropped = im.crop((x0, y0, x1, y1))
    cropped.save(str(png_file), format="PNG")

    # 3. Vision OCR scan metadata
    texts = _scan_canvas_texts(im)
    import json
    metadata = {
        "capture_size": list(im.size),
        "content_roi": {"y0": y0, "y1": y1, "x0": x0, "x1": x1},
        "total_texts": len(texts),
        "texts": texts,
    }
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    return {
        "status": "ok",
        "output_dir": str(dest),
        "files": {
            "pdf": str(pdf_file),
            "png": str(png_file),
            "json": str(json_file),
        },
        "pdf_export": pdf_res,
        "total_texts_scanned": len(texts),
    }


@mcp.tool()
@_serialized_tool
def board_align_to(
    target_query: str,
    item: dict,
    position: str = "below",
    margin: int = 50,
) -> dict:
    """Place a new item relative to an existing element discovered via Vision OCR.

    `target_query`: Text to locate on canvas (e.g. 'Pazaryeri', 'DATABASE').
    `item`: Item dict:
      - text: {"type": "text", "text": "Content", "bold": False}
      - sticky: {"type": "sticky", "text": "Note"}
      - image: {"type": "image", "file_path": "/path/to/img.png"}
      - preset: {"type": "preset", "preset": "arrow_down", "color": "#FF5722"}
    `position`: 'below' | 'above' | 'right_of' | 'left_of'
    `margin`: Margin in capture px between the reference object and the new item.
    """
    ref = board_find_and_select(target_query, select=False)
    if not ref.get("found"):
        return {"status": "error", "message": f"Reference element '{target_query}' not found"}

    cx = ref["center_offset"]["x"]
    cy = ref["center_offset"]["y"]
    box = ref.get("box", {})
    bw = box.get("width", 160)
    bh = box.get("height", 80)

    itype = item.get("type")
    if not itype:
        itype = "image" if "file_path" in item else "text"

    item_w = item.get("width", 200)
    item_h = item.get("height", 100)

    if position == "below":
        new_x = cx
        new_y = cy + (bh / 2) + margin + (item_h / 2)
    elif position == "above":
        new_x = cx
        new_y = cy - (bh / 2) - margin - (item_h / 2)
    elif position == "right_of":
        new_x = cx + (bw / 2) + margin + (item_w / 2)
        new_y = cy
    elif position == "left_of":
        new_x = cx - (bw / 2) - margin - (item_w / 2)
        new_y = cy
    else:
        return {"status": "error", "message": f"Unknown position '{position}', use: below | above | right_of | left_of"}

    tx, ty = int(round(new_x)), int(round(new_y))

    if itype == "image":
        res = image_insert(item.get("file_path"), x=tx, y=ty)
    elif itype == "sticky":
        res = sticky_add(item.get("text", ""), x=tx, y=ty)
    elif itype == "text":
        res = text_add(item.get("text", ""), x=tx, y=ty, bold=item.get("bold", False), italic=item.get("italic", False))
    elif itype == "preset":
        res = shape_insert_preset(
            item.get("preset", "rounded_card"),
            x=tx,
            y=ty,
            color=item.get("color", "#2196F3"),
            label=item.get("label", ""),
            width=item_w,
            height=item_h,
        )
    elif itype == "svg":
        res = shape_svg_insert(item.get("svg", ""), x=tx, y=ty, width=item_w, height=item_h)
    else:
        return {"status": "error", "message": f"Unknown item type '{itype}'"}

    return {
        "status": "ok",
        "reference": {
            "matched_text": ref.get("matched_text"),
            "center": (cx, cy),
        },
        "position": position,
        "target_offset": (tx, ty),
        "result": res,
    }


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
