#!/bin/bash
# Local test stack for NekoMail-on-Ultimit, entirely under a fake HOME:
#   private D-Bus session bus + fake notification server, fake IMAP (+ inject
#   dir), fake SMTP sink, and the NekoMail server itself.
#
#   H=/tmp/claude-1000/mail-home ultimit/tests/stack.sh start|stop|status
#
# Never touches the real HOME/XDG dirs or any real mail server. Stops only
# processes it started (pids in $H/pids).
set -eu
: "${H:?set H to the fake home dir}"
case "$H" in /tmp/*) ;; *) echo "refusing: H must be under /tmp" >&2; exit 1;; esac
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PY="$REPO/backend/.venv/bin/python"
P="$H/pids"; mkdir -p "$P" "$H/run" "$H/fake/inject" "$H/fake/smtp-out" "$H/.config" "$H/.local/share"; chmod 700 "$H/run"
export HOME="$H" XDG_CONFIG_HOME="$H/.config" XDG_DATA_HOME="$H/.local/share" XDG_CACHE_HOME="$H/.cache" XDG_RUNTIME_DIR="$H/run" XDG_STATE_HOME="$H/.local/state"
unset WAYLAND_DISPLAY DISPLAY

bg() {  # bg name cmd... : start detached, save pid
    name=$1; shift
    setsid "$@" > "$H/$name.log" 2>&1 < /dev/null &
    echo $! > "$P/$name.pid"
}
case "${1:-}" in
start)
    dbus-daemon --session --fork --print-address=3 --print-pid=4 3> "$H/dbus.addr" 4> "$P/dbus.pid"
    export DBUS_SESSION_BUS_ADDRESS="$(cat "$H/dbus.addr")"
    : > "$H/notify.log"
    bg notifyd "$PY" "$REPO/ultimit/tests/fake_notify_server.py" --log "$H/notify.log" ${INVOKE_ACTION:+--invoke-action}
    bg imap "$PY" "$REPO/ultimit/tests/fake_imap.py" --port 1143 --inject-dir "$H/fake/inject" --seed
    bg smtp "$PY" "$REPO/ultimit/tests/fake_smtp.py" --port 1025 --out-dir "$H/fake/smtp-out"
    printf '#!/bin/sh\necho "$(date +%%T) window-command invoked" >> "%s/window-cmd.log"\n' "$H" > "$H/window-cmd.sh"; chmod +x "$H/window-cmd.sh"
    WINDOW_COMMAND="$H/window-cmd.sh" bg server "$PY" "$REPO/backend/launcher.py"
    echo "started; bus=$DBUS_SESSION_BUS_ADDRESS" ;;
stop)
    for f in server smtp imap notifyd dbus; do
        [ -f "$P/$f.pid" ] && kill "$(cat "$P/$f.pid")" 2>/dev/null || true
        rm -f "$P/$f.pid"
    done
    echo stopped ;;
account)
    # Link the fake IMAP/SMTP account through the real API (local auto-login).
    B=http://127.0.0.1:8090
    T=$(cat "$XDG_RUNTIME_DIR/nekomail/token")
    TK=$(curl -s -X POST -H "Authorization: Bearer $T" $B/api/auth/local/ticket | "$PY" -c "import sys,json;print(json.load(sys.stdin)['ticket'])")
    curl -s -o /dev/null -c "$H/jar" "$B/api/auth/local/session?ticket=$TK"
    curl -s -b "$H/jar" -X POST -H 'Content-Type: application/json' $B/api/accounts -d '{"label":"Fake Wired","email_address":"me@example.test","imap_host":"127.0.0.1","imap_port":1143,"imap_security":"none","imap_username":"test","imap_password":"test","smtp_host":"127.0.0.1","smtp_port":1025,"smtp_security":"none","smtp_username":"test","smtp_password":"test"}' | head -c 120; echo ;;
status)
    for f in "$P"/*.pid; do n=$(basename "$f" .pid); kill -0 "$(cat "$f")" 2>/dev/null && echo "$n up" || echo "$n down"; done ;;
*) echo "usage: H=... $0 start|stop|status|account" >&2; exit 2 ;;
esac
