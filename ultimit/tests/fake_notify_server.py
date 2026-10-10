"""Fake org.freedesktop.Notifications server for the NekoMail tests (the real
Ultimit shell runs its own). Logs every Notify call to --log (one JSON line
each). With --invoke-action it then emits ActionInvoked(id, "default") +
NotificationClosed, like a user clicking the notification.

Run it on a private session bus (dbus-daemon --session), never the real one."""
import argparse
import json
import sys

from gi.repository import Gio, GLib

XML = """
<node>
 <interface name="org.freedesktop.Notifications">
  <method name="GetCapabilities"><arg direction="out" type="as"/></method>
  <method name="Notify">
   <arg direction="in" type="s"/><arg direction="in" type="u"/><arg direction="in" type="s"/>
   <arg direction="in" type="s"/><arg direction="in" type="s"/><arg direction="in" type="as"/>
   <arg direction="in" type="a{sv}"/><arg direction="in" type="i"/><arg direction="out" type="u"/>
  </method>
  <method name="CloseNotification"><arg direction="in" type="u"/></method>
  <method name="GetServerInformation">
   <arg direction="out" type="s"/><arg direction="out" type="s"/><arg direction="out" type="s"/><arg direction="out" type="s"/>
  </method>
  <signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
  <signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
 </interface>
</node>
"""

ap = argparse.ArgumentParser()
ap.add_argument("--log", required=True)
ap.add_argument("--invoke-action", action="store_true")
args = ap.parse_args()
counter = [0]


def on_call(conn, sender, path, iface, method, params, inv):
    if method == "GetCapabilities":
        inv.return_value(GLib.Variant("(as)", (["actions", "body"],)))
    elif method == "GetServerInformation":
        inv.return_value(GLib.Variant("(ssss)", ("fake-notifd", "nekomail-tests", "1", "1.2")))
    elif method == "Notify":
        app, rid, icon, summary, body, actions, hints, timeout = params.unpack()
        counter[0] += 1
        nid = counter[0]
        with open(args.log, "a") as f:
            f.write(json.dumps({"app": app, "summary": summary, "body": body, "actions": actions,
                                "hints": {k: str(v) for k, v in hints.items()}, "timeout": timeout}) + "\n")
        inv.return_value(GLib.Variant("(u)", (nid,)))
        if args.invoke_action and "default" in actions:
            def fire():
                conn.emit_signal(None, path, iface, "ActionInvoked", GLib.Variant("(us)", (nid, "default")))
                conn.emit_signal(None, path, iface, "NotificationClosed", GLib.Variant("(uu)", (nid, 2)))
                return False
            GLib.timeout_add(400, fire)
    elif method == "CloseNotification":
        inv.return_value(None)


def on_bus(conn, name):
    node = Gio.DBusNodeInfo.new_for_xml(XML)
    conn.register_object("/org/freedesktop/Notifications", node.interfaces[0], on_call, None, None)


Gio.bus_own_name(Gio.BusType.SESSION, "org.freedesktop.Notifications", Gio.BusNameOwnerFlags.REPLACE, on_bus,
                 lambda *a: print("fake notification server ready", flush=True), None)
GLib.MainLoop().run()
