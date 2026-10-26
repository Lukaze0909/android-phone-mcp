#!/usr/bin/env python3
"""
adb_mcp.py — zero-dependency MCP server giving Claude eyes+hands on an Android phone via Shizuku.
Runs inside Termux on the phone itself. Shell commands go through `rish` (Shizuku's shell
client, uid=2000) rather than a separate `adb` wireless-debugging connection — Termux's own
adb client's pairing is unreliable on this device/ROM, while Shizuku's own connection is stable
and survives reboots once set to autostart. Only depends on the Python stdlib + Pillow.

Transport: MCP "Streamable HTTP" — single POST endpoint, JSON-RPC 2.0 in, single JSON response out.
"""

import base64
import io
import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from PIL import Image
except ImportError:
    Image = None

PORT = int(os.environ.get("ADB_MCP_PORT", "8765"))
PROTOCOL_VERSION = "2025-03-26"
ADBKEYBOARD_IME = "com.android.adbkeyboard/.AdbIME"
RISH_PATH = os.path.expanduser(os.environ.get("RISH_PATH", "~/.rish/assets/rish"))
# RISH_APPLICATION_ID must be the package name of the app that *calls* rish (Termux),
# NOT Shizuku's own package name — getting this wrong shows up as a silent "Request timeout".
RISH_ENV = dict(os.environ, RISH_APPLICATION_ID=os.environ.get("RISH_APPLICATION_ID", "com.termux"))


def adb(*args, timeout=15, binary=False):
    """Run a shell command through rish (Shizuku), keeping the old adb-style call signature.
    `args` is treated like `adb shell <args>` / `adb exec-out <args>` used to be: the last
    element is the actual command string; a leading 'shell'/'exec-out' token (if present) is
    ignored since rish always drops you straight into a uid=2000 shell."""
    cmd = args[-1] if args else ""
    try:
        result = subprocess.run(
            [RISH_PATH],
            input=cmd.encode() if isinstance(cmd, str) else cmd,
            capture_output=True,
            timeout=timeout,
            env=RISH_ENV,
        )
    except subprocess.TimeoutExpired:
        return False, "rish command timed out"
    except FileNotFoundError:
        return False, f"rish binary not found at {RISH_PATH} (did the Shizuku setup steps run?)"
    if result.returncode != 0:
        return False, result.stderr.decode(errors="replace").strip() or "rish failed"
    if binary:
        return True, result.stdout
    return True, result.stdout.decode(errors="replace")


def adb_shell(cmd, timeout=15):
    return adb("shell", cmd, timeout=timeout)


# Screenshot scratch file: written by `screencap` (via rish) to shared storage, then read back
# directly by Termux through the ~/storage/shared symlink created by `termux-setup-storage`.
SS_NAME = os.environ.get("ADB_MCP_SS_NAME", "adb_mcp_ss.png")
TMP_SS_PATH = f"/sdcard/{SS_NAME}"

# Coordinates for click/swipe/long_press/rapid_tap are always given in "screenshot space"
# (the pixel grid of the last image tool_screenshot returned), never native device pixels.
# tool_screenshot updates this whenever it resizes the image; every coordinate-based tool
# divides by it before talking to the real device. This is the fix for an earlier bug
# where scale=0.75 screenshots were being fed straight into `input tap` as if 1:1, causing
# every tap to land systematically up-and-left of the intended target (worse near edges).
_LAST_SCREENSHOT_SCALE = 1.0


def _to_device_coords(x, y):
    s = _LAST_SCREENSHOT_SCALE or 1.0
    return int(round(x / s)), int(round(y / s))


def tool_screenshot(quality=75, scale=0.75):
    # rish's stdout relay is unreliable for bulk data on this device — a raw `screencap -p`
    # pipe gets corrupted, and even reading a large base64-encoded file back through rish
    # comes back scrambled (confirmed on real hardware: garbage from byte 0, consistent with
    # rish silently dropping/misordering chunks of large output). rish is fine for short
    # trigger commands, just not for relaying tens/hundreds of KB of text.
    # Workaround: use rish only to trigger `screencap` writing to shared storage (/sdcard),
    # then read that file directly with Termux's own unprivileged Python file I/O — no rish
    # involved in moving the actual bytes, so its output-relay bug never comes into play.
    ok, out = adb_shell(f"screencap -p {TMP_SS_PATH}", timeout=15)
    if not ok:
        return err_content(f"screencap step failed: {out}")
    local_path = os.path.expanduser(f"~/storage/shared/{SS_NAME}")
    try:
        with open(local_path, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return err_content(
            f"couldn't read {local_path} from Termux — has `termux-setup-storage` been run "
            "(grants Termux the shared-storage permission + creates ~/storage symlinks)?"
        )
    adb_shell(f"rm -f {TMP_SS_PATH}", timeout=5)
    if Image is None:
        return err_content("Pillow not installed (pkg install python-pillow)")
    if len(raw) < 100:
        return err_content(f"DEBUG raw too short: len={len(raw)}")
    global _LAST_SCREENSHOT_SCALE
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        if scale and scale != 1.0:
            w, h = img.size
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        _LAST_SCREENSHOT_SCALE = float(scale) if scale else 1.0
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=int(quality), optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        return err_content(f"image processing failed: {e}; raw_len={len(raw)}; raw_head={raw[:16]!r}")
    return {"content": [{"type": "image", "data": b64, "mimeType": "image/jpeg"}]}


def tool_click(x, y):
    dx, dy = _to_device_coords(x, y)
    ok, out = adb_shell(f"input tap {dx} {dy}")
    return ok_or_err(ok, out, f"tapped screenshot-coords ({x},{y}) -> device ({dx},{dy})")


def tool_long_press(x, y, duration_ms=800):
    dx, dy = _to_device_coords(x, y)
    ok, out = adb_shell(f"input swipe {dx} {dy} {dx} {dy} {int(duration_ms)}")
    return ok_or_err(ok, out, f"long-pressed screenshot-coords ({x},{y}) -> device ({dx},{dy}) for {duration_ms}ms")


def tool_swipe(x1, y1, x2, y2, duration_ms=300):
    dx1, dy1 = _to_device_coords(x1, y1)
    dx2, dy2 = _to_device_coords(x2, y2)
    ok, out = adb_shell(
        f"input swipe {dx1} {dy1} {dx2} {dy2} {int(duration_ms)}"
    )
    return ok_or_err(ok, out, f"swiped screenshot-coords ({x1},{y1})->({x2},{y2}) -> device ({dx1},{dy1})->({dx2},{dy2})")


def tool_rapid_tap(x, y, count=20, interval_ms=50):
    dx, dy = _to_device_coords(x, y)
    count = max(1, min(int(count), 100))
    for _ in range(count):
        adb_shell(f"input tap {dx} {dy}", timeout=5)
        time.sleep(max(0, int(interval_ms)) / 1000.0)
    return ok_or_err(True, "", f"tapped screenshot-coords ({x},{y}) -> device ({dx},{dy}) x{count}")


def tool_type_text(text):
    escaped = str(text).replace(" ", "%s")
    ok, out = adb_shell(f"input text '{escaped}'")
    return ok_or_err(ok, out, f"typed ascii text ({len(text)} chars)")


ADBKEYBOARD_PKG = "com.android.adbkeyboard"


def tool_type_chinese(text):
    ok, prev_ime = adb_shell("settings get secure default_input_method")
    prev_ime = prev_ime.strip() if ok else ""
    ok, out = adb_shell(f"ime set {ADBKEYBOARD_IME}")
    # `ime set` only prints "...selected for user #0" when it actually changes the active
    # IME — it prints nothing if ADBKeyBoard was already active, which isn't a failure. Trust
    # the exit code alone; don't require specific output text.
    if not ok:
        return err_content(f"could not switch to ADBKeyBoard: {out!r}. Is it installed and enabled?")
    time.sleep(1.2)
    b64 = base64.b64encode(str(text).encode("utf-8")).decode()
    # explicit package target (-p): Android 8+ restricts implicit broadcasts reaching
    # manifest-registered receivers in apps that aren't in the foreground, which silently
    # swallowed this broadcast on real hardware (am broadcast reported success, nothing typed).
    ok, out = adb_shell(f"am broadcast -p {ADBKEYBOARD_PKG} -a ADB_INPUT_B64 --es msg '{b64}'")
    time.sleep(0.3)
    if prev_ime and prev_ime not in ("null", ""):
        adb_shell(f"ime set {prev_ime}")
    return ok_or_err(ok, out, f"typed chinese/unicode text ({len(text)} chars); broadcast result: {out.strip()}")


def tool_clear_input():
    ok, out = adb_shell(f"am broadcast -a ADB_CLEAR_TEXT")
    return ok_or_err(ok, out, "cleared focused input field")


def tool_key_event(keycode):
    ok, out = adb_shell(f"input keyevent {keycode}")
    return ok_or_err(ok, out, f"sent keyevent {keycode}")


def tool_open_app(package):
    ok, out = adb_shell(
        f"monkey -p {package} -c android.intent.category.LAUNCHER 1"
    )
    return ok_or_err(ok, out, f"launched {package}")


def tool_close_app(package):
    ok, out = adb_shell(f"am force-stop {package}")
    return ok_or_err(ok, out, f"force-stopped {package}")


def tool_list_apps(system=False):
    flag = "" if system else "-3"
    ok, out = adb_shell(f"pm list packages {flag}".strip())
    if not ok:
        return err_content(out)
    pkgs = [line.replace("package:", "").strip() for line in out.splitlines() if line.strip()]
    return {"content": [{"type": "text", "text": "\n".join(sorted(pkgs))}]}


def tool_screen_info():
    ok1, size = adb_shell("wm size")
    ok2, density = adb_shell("wm density")
    if not (ok1 and ok2):
        return err_content(f"{size} / {density}")
    return {"content": [{"type": "text", "text": f"{size.strip()}\n{density.strip()}"}]}


def ok_or_err(ok, out, success_msg):
    if not ok:
        return err_content(out)
    return {"content": [{"type": "text", "text": success_msg}]}


def err_content(msg):
    return {"content": [{"type": "text", "text": f"ERROR: {msg}"}], "isError": True}


TOOLS = {
    "screenshot": {
        "description": "Take a screenshot of the phone screen. Compressed JPEG (default 75% quality, 75% scale) to keep token cost low.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "quality": {"type": "integer", "description": "JPEG quality 1-100, default 75"},
                "scale": {"type": "number", "description": "Resize factor 0-1, default 0.75"},
            },
        },
        "handler": lambda a: tool_screenshot(a.get("quality", 75), a.get("scale", 0.75)),
    },
    "click": {
        "description": "Tap the screen at (x, y). Call screen_info first to know valid coordinate ranges.",
        "inputSchema": {
            "type": "object",
            "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
            "required": ["x", "y"],
        },
        "handler": lambda a: tool_click(a["x"], a["y"]),
    },
    "long_press": {
        "description": "Long-press the screen at (x, y).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "duration_ms": {"type": "integer", "description": "default 800"},
            },
            "required": ["x", "y"],
        },
        "handler": lambda a: tool_long_press(a["x"], a["y"], a.get("duration_ms", 800)),
    },
    "swipe": {
        "description": "Swipe from (x1,y1) to (x2,y2).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x1": {"type": "integer"}, "y1": {"type": "integer"},
                "x2": {"type": "integer"}, "y2": {"type": "integer"},
                "duration_ms": {"type": "integer", "description": "default 300"},
            },
            "required": ["x1", "y1", "x2", "y2"],
        },
        "handler": lambda a: tool_swipe(a["x1"], a["y1"], a["x2"], a["y2"], a.get("duration_ms", 300)),
    },
    "rapid_tap": {
        "description": "Tap the same point repeatedly, fast. Useful for gacha pulls, skip animations, chest opening.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"}, "y": {"type": "integer"},
                "count": {"type": "integer", "description": "default 20, max 100"},
                "interval_ms": {"type": "integer", "description": "default 50"},
            },
            "required": ["x", "y"],
        },
        "handler": lambda a: tool_rapid_tap(a["x"], a["y"], a.get("count", 20), a.get("interval_ms", 50)),
    },
    "type_text": {
        "description": "Type ASCII text into the currently focused input field. Faster than type_chinese, English/numbers only.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "handler": lambda a: tool_type_text(a["text"]),
    },
    "type_chinese": {
        "description": "Type Chinese/Unicode/emoji text into the currently focused input field, via ADBKeyBoard. Requires ADBKeyBoard app installed (input method enabled, doesn't need to be default).",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "handler": lambda a: tool_type_chinese(a["text"]),
    },
    "clear_input": {
        "description": "Clear the text in the currently focused input field (via ADBKeyBoard).",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: tool_clear_input(),
    },
    "key_event": {
        "description": "Send a raw Android keyevent code, e.g. 4=BACK, 3=HOME, 26=POWER/wake, 66=ENTER, 67=DEL.",
        "inputSchema": {
            "type": "object",
            "properties": {"keycode": {"type": "integer"}},
            "required": ["keycode"],
        },
        "handler": lambda a: tool_key_event(a["keycode"]),
    },
    "open_app": {
        "description": "Launch an app by Android package name (use list_apps to find it).",
        "inputSchema": {
            "type": "object",
            "properties": {"package": {"type": "string"}},
            "required": ["package"],
        },
        "handler": lambda a: tool_open_app(a["package"]),
    },
    "close_app": {
        "description": "Force-stop an app by package name.",
        "inputSchema": {
            "type": "object",
            "properties": {"package": {"type": "string"}},
            "required": ["package"],
        },
        "handler": lambda a: tool_close_app(a["package"]),
    },
    "list_apps": {
        "description": "List installed app package names. Defaults to user-installed (third-party) apps only.",
        "inputSchema": {
            "type": "object",
            "properties": {"system": {"type": "boolean", "description": "include system apps too, default false"}},
        },
        "handler": lambda a: tool_list_apps(a.get("system", False)),
    },
    "screen_info": {
        "description": "Get screen resolution and density. Call this first to know coordinate ranges before tapping.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: tool_screen_info(),
    },
}


def handle_rpc(req):
    method = req.get("method")
    req_id = req.get("id")
    is_notification = req_id is None

    if method == "initialize":
        result = {
            "protocolVersion": req.get("params", {}).get("protocolVersion", PROTOCOL_VERSION),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "adb-mcp", "version": "1.0.0"},
        }
        return rpc_result(req_id, result)

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        tools_list = [
            {"name": name, "description": t["description"], "inputSchema": t["inputSchema"]}
            for name, t in TOOLS.items()
        ]
        return rpc_result(req_id, {"tools": tools_list})

    if method == "tools/call":
        params = req.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {}) or {}
        tool = TOOLS.get(name)
        if not tool:
            return rpc_error(req_id, -32602, f"unknown tool: {name}")
        try:
            result = tool["handler"](args)
        except Exception as e:
            result = err_content(str(e))
        return rpc_result(req_id, result)

    if is_notification:
        return None
    return rpc_error(req_id, -32601, f"unknown method: {method}")


def rpc_result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def rpc_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f"[adb_mcp] {fmt % args}\n")

    def do_GET(self):
        if self.path == "/health":
            ok, out = adb_shell("id", timeout=5)
            body = json.dumps({
                "status": "ok",
                "rish": ok,
                "rish_identity": out.strip() if ok else out,
                "pillow": Image is not None,
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            req = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        resp = handle_rpc(req)

        if resp is None:
            self.send_response(202)
            self.end_headers()
            return

        body = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"adb_mcp listening on 127.0.0.1:{PORT}  (Pillow: {Image is not None})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
