#!/bin/bash
# Install NekoMail as Ultimit's mail app. No root needed.
#
#   sh ultimit/install-ultimit.sh
#
# Builds the frontend, creates backend/.venv (--system-site-packages, so
# pywebview's GTK backend sees the system PyGObject + WebKitGTK), installs
# the `nekomail` window launcher, the nekomail.service systemd user unit, the
# .desktop entry and icons.
#
# Overrides (all optional):
#   DEST=<dir>          install everything under <dir> (config/data/bin) instead of $HOME
#                       -- used for testing into a fake home; skips systemctl
#   XDG_CONFIG_HOME / XDG_DATA_HOME / BIN_DIR   individual locations
#   SKIP_FRONTEND=1     don't run npm (reuse backend/app/static as it is)
#   NO_SYSTEMCTL=1      write the unit but don't touch the user manager
#   START=1             also `systemctl --user enable --now nekomail`
#   NO_APT=1            don't try to apt-install the GTK/WebKit packages
set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$REPO/backend"
FRONTEND="$REPO/frontend"
VENV="$BACKEND/.venv"

if [ -n "${DEST:-}" ]; then
    CONFIG_HOME="${XDG_CONFIG_HOME:-$DEST/.config}"
    DATA_HOME="${XDG_DATA_HOME:-$DEST/.local/share}"
    BIN="${BIN_DIR:-$DEST/.local/bin}"
    NO_SYSTEMCTL=1
else
    CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
    DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
    BIN="${BIN_DIR:-$HOME/.local/bin}"
fi
NO_SYSTEMCTL="${NO_SYSTEMCTL:-0}"

# The window is pywebview on GTK: it needs the system PyGObject + WebKitGTK 4.1
# (the venv sees them through --system-site-packages). Without them `nekomail`
# exits at once, so install them (pkexec asks for the password) or stop here.
SYS_PKGS="python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1"
gtk_ok() {
    python3 -c 'import gi; gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1"); from gi.repository import Gtk, WebKit2' 2>/dev/null
}
echo "[0/5] System packages ($SYS_PKGS)"
if gtk_ok; then
    echo "  present"
elif [ "${NO_APT:-0}" != "1" ] && command -v apt-get >/dev/null 2>&1; then
    if [ "$(id -u)" = "0" ]; then apt-get install -y $SYS_PKGS
    elif command -v pkexec >/dev/null 2>&1 && [ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]; then pkexec apt-get install -y $SYS_PKGS
    else sudo apt-get install -y $SYS_PKGS
    fi || true
fi
gtk_ok || { echo "PyGObject/WebKitGTK missing; the NekoMail window can't open. Install them with:" >&2
            echo "  sudo apt install $SYS_PKGS" >&2; exit 1; }

echo "[1/5] Frontend"
if [ "${SKIP_FRONTEND:-0}" = "1" ]; then
    echo "  skipped (SKIP_FRONTEND=1); using $BACKEND/app/static"
else
    command -v npm >/dev/null 2>&1 || { echo "npm not found: install Node.js, or set SKIP_FRONTEND=1" >&2; exit 1; }
    cd "$FRONTEND"
    if [ -f package-lock.json ]; then npm ci; else npm install; fi
    npm run build
    rm -rf "$BACKEND/app/static"
    cp -r "$FRONTEND/dist" "$BACKEND/app/static"
fi
[ -f "$BACKEND/app/static/index.html" ] || echo "  warning: $BACKEND/app/static/index.html missing: the server will serve the API only" >&2

echo "[2/5] Python venv ($(python3 --version))"
if [ ! -x "$VENV/bin/python" ]; then
    if ! python3 -m venv --system-site-packages "$VENV" 2>/dev/null; then
        # No python3-venv/ensurepip (and no sudo): create it without pip and
        # bootstrap pip from PyPI.
        rm -rf "$VENV"
        python3 -m venv --system-site-packages --without-pip "$VENV"
        "$VENV/bin/python" "$REPO/ultimit/bootstrap_pip.py"
    fi
fi
"$VENV/bin/python" -m pip install --quiet --prefer-binary -r "$BACKEND/requirements-linux.txt"
"$VENV/bin/python" - <<'PY' || { echo "PyGObject/WebKitGTK not importable from $VENV (apt: $SYS_PKGS); the window won't open" >&2; exit 1; }
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, WebKit2
PY

echo "[3/5] Launcher: $BIN/nekomail"
mkdir -p "$BIN"
cat > "$BIN/nekomail" <<EOF
#!/bin/sh
# NekoMail window (single instance). Starts the sync server if needed.
# Wayland: talk to the compositor directly (not XWayland) so the app_id is "nekomail".
[ -n "\${WAYLAND_DISPLAY:-}" ] && export GDK_BACKEND="\${GDK_BACKEND:-wayland}"
exec "$VENV/bin/python" "$BACKEND/desktop_app.py" "\$@"
EOF
chmod +x "$BIN/nekomail"

echo "[4/5] systemd user unit"
UNIT_DIR="$CONFIG_HOME/systemd/user"
mkdir -p "$UNIT_DIR"
sed -e "s|@REPO@|$REPO|g" -e "s|@BACKEND@|$BACKEND|g" -e "s|@BIN@|$BIN|g" \
    "$REPO/ultimit/nekomail.service" > "$UNIT_DIR/nekomail.service"
echo "  $UNIT_DIR/nekomail.service"
if [ "$NO_SYSTEMCTL" = "1" ]; then
    echo "  (not touching the user manager; enable with: systemctl --user enable --now nekomail)"
elif command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload
    if [ "${START:-0}" = "1" ]; then systemctl --user enable --now nekomail.service
    else systemctl --user enable nekomail.service; echo "  enabled; start now with: systemctl --user start nekomail"; fi
fi

echo "[5/5] Desktop entry + icons"
APPS="$DATA_HOME/applications"
ICONS="$DATA_HOME/icons/hicolor"
mkdir -p "$APPS" "$ICONS/scalable/apps" "$ICONS/192x192/apps" "$ICONS/512x512/apps"
cp "$REPO/ultimit/nekomail.svg" "$ICONS/scalable/apps/nekomail.svg"
cp "$FRONTEND/public/icons/icon-192.png" "$ICONS/192x192/apps/nekomail.png"
cp "$FRONTEND/public/icons/icon-512.png" "$ICONS/512x512/apps/nekomail.png"
cat > "$APPS/nekomail.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=NekoMail
GenericName=Mail
Comment=Mail client (Ultimit MAILER)
Exec=$BIN/nekomail %u
Icon=nekomail
Terminal=false
Categories=Network;Email;
StartupWMClass=nekomail
StartupNotify=false
MimeType=x-scheme-handler/mailto;
EOF
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$ICONS" 2>/dev/null || true

# Become the mailto: handler unless the user already picked another mail app.
if [ -z "${DEST:-}" ] && command -v xdg-mime >/dev/null 2>&1; then
    cur="$(xdg-mime query default x-scheme-handler/mailto 2>/dev/null || true)"
    if [ -z "$cur" ] || [ "$cur" = "nekomail.desktop" ]; then
        xdg-mime default nekomail.desktop x-scheme-handler/mailto && echo "  default mailto: handler"
    else
        echo "  mailto: stays with $cur (switch in Settings > Default apps)"
    fi
fi

echo
echo "NekoMail installed. Window: $BIN/nekomail  (make sure $BIN is on PATH)"
echo "Config: $CONFIG_HOME/nekomail/config.env   Data: $DATA_HOME/nekomail/"
