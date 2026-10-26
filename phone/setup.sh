#!/data/data/com.termux/files/usr/bin/bash
# setup.sh — one-time dependency install for adb_mcp. Run once after termux-change-repo.
set -e

pkg update -y
pkg install -y python android-tools openssh python-pillow autossh

if [ ! -f ~/.ssh/id_ed25519 ]; then
    echo "No SSH key found, generating one..."
    ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
fi

echo ""
echo "=== setup done ==="
echo "Your SSH public key (send this to the VPS operator to authorize):"
cat ~/.ssh/id_ed25519.pub
echo ""
echo "Next: edit qi.sh's config block (VPS_HOST etc), then run: bash qi.sh"
