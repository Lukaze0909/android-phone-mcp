#!/data/data/com.termux/files/usr/bin/bash
# qi.sh — one-command "go online": wake-lock + rish(Shizuku) check + adb_mcp + SSH reverse tunnel.

# ==== config (edit these, or export the same names as env vars before running) ====
MCP_PORT="${MCP_PORT:-8765}"                 # phone-local port, must match adb_mcp.py (ADB_MCP_PORT)
VPS_PORT="${VPS_PORT:-18080}"                # port bound on the VPS loopback, must match nginx proxy_pass
VPS_USER="${VPS_USER:-<YOUR_VPS_USER>}"      # VPS login user that holds the phone's SSH public key
VPS_HOST="${VPS_HOST:-<YOUR_VPS_HOST>}"      # VPS domain or IP
VPS_SSH_PORT="${VPS_SSH_PORT:-2222}"         # port 22 gets blocked outbound by some proxy nodes, 2222 is the workaround
RISH_APPLICATION_ID="${RISH_APPLICATION_ID:-com.termux}"  # package name of the CALLER (Termux), not Shizuku
# ==================================================================================

case "$VPS_HOST$VPS_USER" in
    *"<YOUR_"*) echo "!! edit the config block at the top of qi.sh (VPS_HOST / VPS_USER) first."; exit 1 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$HOME/.adb_mcp_logs"
RISH="$HOME/.rish/assets/rish"
mkdir -p "$LOG_DIR"

termux-wake-lock

echo "[1/4] checking Shizuku/rish connection..."
if [ ! -x "$RISH" ]; then
    echo "  !! $RISH not found or not executable. Re-run the rish extraction step first."
    exit 1
fi
RISH_ID=$(echo "id" | RISH_APPLICATION_ID="$RISH_APPLICATION_ID" "$RISH" 2>&1)
if ! echo "$RISH_ID" | grep -q "uid="; then
    echo "  !! rish didn't return a shell identity. Output was:"
    echo "     $RISH_ID"
    echo "     Open the Shizuku app and tap Start (or Pair first if it needs re-pairing), then re-run this script."
    exit 1
fi
echo "  ok: $RISH_ID"

echo "[2/4] starting adb_mcp.py..."
if pgrep -f "python.*adb_mcp.py" >/dev/null; then
    echo "  already running."
else
    ADB_MCP_PORT="$MCP_PORT" RISH_APPLICATION_ID="$RISH_APPLICATION_ID" \
        nohup python3 "$SCRIPT_DIR/adb_mcp.py" > "$LOG_DIR/adb_mcp.log" 2>&1 &
    disown
    sleep 1
fi

echo "[3/4] starting SSH reverse tunnel (autossh)..."
if pgrep -f "autossh.*$VPS_PORT:localhost:$MCP_PORT" >/dev/null; then
    echo "  already running."
else
    AUTOSSH_GATETIME=0 nohup autossh -M 0 -p "$VPS_SSH_PORT" \
        -o "ServerAliveInterval=15" -o "ServerAliveCountMax=3" \
        -o "ExitOnForwardFailure=yes" -o "StrictHostKeyChecking=accept-new" \
        -N -R "$VPS_PORT:localhost:$MCP_PORT" "$VPS_USER@$VPS_HOST" \
        > "$LOG_DIR/autossh.log" 2>&1 &
    disown
    sleep 2
fi

echo "[4/4] status check..."
sleep 1
curl -s "http://127.0.0.1:$MCP_PORT/health" || echo "  (local health check failed, check $LOG_DIR/adb_mcp.log)"
echo ""
echo "Done. If pillow/rish above both say true, you're online."
echo "Public URL (only works with the auth token configured in nginx): https://$VPS_HOST/phone/"
