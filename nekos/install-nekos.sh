#!/bin/sh
# NekoMail installer for nekOS (Void Linux, run inside the nekos-void WSL2
# distro). Run as root: sh nekos/install-nekos.sh
#
# Builds the Vue frontend and creates a Python venv in place under
# /opt/nekomail (assumes this repo has already been synced there -- see
# nekos/README.md for the host-side robocopy command). No PyInstaller here,
# unlike the Windows desktop app: this distro already has its own python3,
# so running straight from the venv's interpreter is enough for a personal
# install (same choice NekoShot already made for its own nekos/install-nekos.sh).
#
# Does NOT start the server or write the .desktop entry -- that's nekOS's
# own provision/install-nekomail.sh, run every session start from
# start-session.sh (mirrors how install-nekoshot.sh/install-nekoplayer.sh
# split "install the app" from "wire it into this session").
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: please run as root (sudo sh nekos/install-nekos.sh)" >&2
    exit 1
fi

# This script lives in nekos/, one level below the repo root (same layout
# as NekoShot's nekos/install-nekos.sh).
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_DIR/backend"
FRONTEND_DIR="$REPO_DIR/frontend"
VENV_DIR="$BACKEND_DIR/.venv"
BIN_DIR="/usr/local/bin"

echo "[1/5] Installing system dependencies..."
# libwebkit2gtk41/python3-gobject back pywebview's GTK backend (the native
# window desktop_app.py opens) -- these have to be system packages, not pip,
# which is why the venv below is --system-site-packages. Confirmed live
# against this distro's xbps repo (2026-08-04): plain "webkit2gtk" doesn't
# exist as a package name here -- it's "libwebkit2gtk41" (GTK+3 port, soup3;
# there's also a GTK4-only "libwebkitgtk60" which pywebview's GTK backend
# does not use). Re-check with `xbps-query -Rs webkit` / `-Rs python3-gobject`
# if this ever breaks on a future Void repo snapshot.
#
# noto-fonts-emoji: NekoMail's whole icon system is plain emoji characters
# (Compose/folder icons, empty-state art -- see FolderSidebar.vue/
# MessageList.vue/ReadingPane.vue), not an icon font or SVG set. Void's
# baseline has no emoji glyphs at all (dejavu-fonts-ttf doesn't cover them),
# so without this WebKitGTK renders every one of them as blank space --
# confirmed live (2026-08-05), looked exactly like a missing-icon bug but
# was actually a missing-font one.
xbps-install -Sy \
    python3 \
    python3-devel \
    python3-pip \
    nodejs \
    libwebkit2gtk41 \
    python3-gobject \
    gtk+3 \
    noto-fonts-emoji

echo
echo "[2/5] Building the frontend..."
cd "$FRONTEND_DIR"
npm install
npm run build

echo
echo "[3/5] Copying frontend build into backend/app/static..."
STATIC_DIR="$BACKEND_DIR/app/static"
rm -rf "$STATIC_DIR"
cp -r "$FRONTEND_DIR/dist" "$STATIC_DIR"

echo
echo "[4/5] Creating Python venv and installing dependencies..."
# --system-site-packages: see the webkit2gtk/python3-gobject note above --
# pywebview's GTK backend needs to see those, not just what pip can install.
python3 -m venv --system-site-packages "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip

# requirements.txt pins two packages that don't work as-is on this distro's
# python3 (3.14, confirmed live 2026-08-04 -- newer than Docker's Python
# 3.12 / the Windows desktop app's Python 3.13 that these pins were chosen
# against):
#   - pydantic==2.10.3 hard-pins pydantic-core==2.27.1, which has no
#     prebuilt wheel for cp314. pip falls back to building it from source
#     (Rust/maturin), which fails outright: PyO3 0.22.x's max supported
#     Python is 3.13, full stop, not a missing-toolchain problem more
#     `xbps-install`ing could fix.
#   - sqlalchemy==2.0.36's declarative-mapping code (`Mapped[X | None]`
#     annotation scanning) hits a real Python 3.14 `typing` incompatibility
#     at import time (`TypeError: descriptor '__getitem__' requires a
#     'typing.Union' object but received a 'tuple'`) -- not a missing-wheel
#     problem, a genuine version-compat bug fixed in later 2.0.x patches.
# Both have newer releases that work fine here (confirmed live) and fastapi/
# pydantic-settings/alembic all accept a broad pydantic/sqlalchemy 2.x range,
# so: install everything else exactly as pinned, then let these two float to
# whatever this Python actually works with. (cryptography/bcrypt don't have
# this problem -- both ship Python-version-independent abi3 wheels.)
grep -v -E '^(pydantic|sqlalchemy)(\[|==)' "$BACKEND_DIR/requirements.txt" > /tmp/nekomail-requirements-linux.txt
# pywebview: the viewer window. pillow: desktop_app.py's _load_icon() uses
# PIL.Image unconditionally (both platforms), same as Windows'
# requirements-desktop.txt -- easy to miss since it's not imported by
# anything in plain requirements.txt. No pystray, no pyinstaller here --
# Windows-only (see desktop_app.py's module docstring for why hide-to-tray
# doesn't carry over to nekOS).
"$VENV_DIR/bin/pip" install -r /tmp/nekomail-requirements-linux.txt pywebview pillow
"$VENV_DIR/bin/pip" install "pydantic>=2.10,<3" "sqlalchemy[asyncio]>=2.0"
rm -f /tmp/nekomail-requirements-linux.txt

echo
echo "[5/5] Installing command wrappers..."
cat > "$BIN_DIR/nekomail-server" << EOF
#!/bin/sh
# Runs the NekoMail backend in the foreground -- for manual testing/
# debugging. The real session-start launch is provision/install-nekomail.sh
# (in nekOS's own repo), which backgrounds this same launcher.py.
exec "$VENV_DIR/bin/python" "$BACKEND_DIR/launcher.py"
EOF
chmod +x "$BIN_DIR/nekomail-server"

cat > "$BIN_DIR/nekomail" << EOF
#!/bin/sh
# Opens the NekoMail viewer window against the already-running background
# server (see desktop_app.py's module docstring -- this does NOT start a
# server itself on Linux).
exec "$VENV_DIR/bin/python" "$BACKEND_DIR/desktop_app.py"
EOF
chmod +x "$BIN_DIR/nekomail"

echo
echo "========================================"
echo "NekoMail installed."
echo "========================================"
echo
echo "Data/config: \$HOME/.nekomail/ (config.env + data/{nekomail.db,mail/})"
echo "First run (nekomail-server, in the foreground) creates config.env with"
echo "a placeholder ADMIN_PASSWORD -- edit it to a real password, then"
echo "restart. See ../NEXT_STEPS.md's standalone-packaging section for the"
echo "same first-run flow on Windows; it's identical here."
echo
echo "Normally you don't run either wrapper by hand -- nekOS's own"
echo "provision/install-nekomail.sh starts nekomail-server in the background"
echo "at session start, and the 'NekoMail' entry in nekos-launch runs"
echo "nekomail (the viewer window) against it. See nekos/README.md."
