// Small reconnecting WebSocket client for the server's push channel
// (services/ws_manager.py). Mirrors the backend watcher's own capped-backoff
// reconnect philosophy (see services/mail/scheduler.py).
const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000];

export function connectWs(onMessage) {
  let socket = null;
  let attempt = 0;
  let closed = false;
  let reconnectTimer = null;

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${protocol}//${window.location.host}/ws`;

  function open() {
    if (closed) return;
    socket = new WebSocket(url);

    socket.onopen = () => {
      attempt = 0;
    };
    socket.onmessage = (event) => {
      try {
        onMessage(JSON.parse(event.data));
      } catch {
        // Ignore malformed frames.
      }
    };
    socket.onclose = () => {
      if (closed) return;
      const delay = RECONNECT_DELAYS_MS[Math.min(attempt, RECONNECT_DELAYS_MS.length - 1)];
      attempt += 1;
      reconnectTimer = setTimeout(open, delay);
    };
    socket.onerror = () => {
      socket?.close();
    };
  }

  open();

  return function close() {
    closed = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    socket?.close();
  };
}
