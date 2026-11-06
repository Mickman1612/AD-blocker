"""A small Chrome DevTools Protocol client using only the standard library."""
import base64
import itertools
import json
import os
import queue
import socket
import struct
import threading
import urllib.parse


class WebSocket:
    """Just enough of RFC 6455 to talk to a browser on localhost."""

    def __init__(self, url, timeout=30):
        parts = urllib.parse.urlparse(url)
        self._sock = socket.create_connection((parts.hostname, parts.port), timeout=timeout)
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._reader = self._sock.makefile("rb")
        self._send_lock = threading.Lock()
        key = base64.b64encode(os.urandom(16)).decode()
        self._sock.sendall((
            f"GET {parts.path} HTTP/1.1\r\n"
            f"Host: {parts.hostname}:{parts.port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        status = self._reader.readline()
        if b" 101 " not in status:
            raise ConnectionError(f"WebSocket upgrade refused: {status!r}")
        while self._reader.readline().strip():
            pass
        self._sock.settimeout(None)

    def send(self, text):
        self._send_frame(0x1, text.encode("utf-8"))

    def _send_frame(self, opcode, payload):
        length = len(payload)
        if length < 126:
            header = struct.pack("!BB", 0x80 | opcode, 0x80 | length)
        elif length < 65536:
            header = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, length)
        mask = os.urandom(4)
        repeated = (mask * (length // 4 + 1))[:length]
        masked = (int.from_bytes(payload, "big") ^ int.from_bytes(repeated, "big")).to_bytes(length, "big")
        with self._send_lock:
            self._sock.sendall(header + mask + masked)

    def recv(self):
        """Return the next complete text message, or None once the socket closes."""
        parts = []
        while True:
            head = self._reader.read(2)
            if len(head) < 2:
                return None
            fin, opcode = head[0] & 0x80, head[0] & 0x0F
            length = head[1] & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._reader.read(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._reader.read(8))[0]
            payload = self._reader.read(length)
            if opcode == 0x8:
                return None
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            parts.append(payload)
            if fin:
                return b"".join(parts).decode("utf-8")

    def close(self):
        try:
            self._reader.close()
            self._sock.close()
        except OSError:
            pass


class Cdp:
    """One browser connection. Replies and events are handled on separate threads,
    so an event callback may safely call send()."""

    def __init__(self, url):
        self._ws = WebSocket(url)
        self._ids = itertools.count(1)
        self._pending = {}
        self._lock = threading.Lock()
        self._listeners = []
        self._events = queue.Queue()
        threading.Thread(target=self._read_loop, daemon=True).start()
        threading.Thread(target=self._event_loop, daemon=True).start()

    def send(self, method, params=None, session_id=None, timeout=30):
        message_id = next(self._ids)
        reply = queue.Queue(1)
        with self._lock:
            self._pending[message_id] = reply
        message = {"id": message_id, "method": method, "params": params or {}}
        if session_id:
            message["sessionId"] = session_id
        self._ws.send(json.dumps(message))
        try:
            result = reply.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"No reply to {method} within {timeout}s") from None
        finally:
            with self._lock:
                self._pending.pop(message_id, None)
        if "error" in result:
            raise RuntimeError(f"{method}: {result['error'].get('message')}")
        return result.get("result", {})

    def on(self, method, callback, session_id=None):
        self._listeners.append((method, session_id, callback))

    def _read_loop(self):
        while True:
            try:
                text = self._ws.recv()
            except (OSError, ValueError):  # A closed socket is the normal way to end.
                text = None
            if text is None:
                self._events.put(None)
                with self._lock:
                    pending = list(self._pending.values())
                for reply in pending:
                    reply.put({"error": {"message": "connection closed"}})
                return
            message = json.loads(text)
            if "id" in message:
                with self._lock:
                    reply = self._pending.get(message["id"])
                if reply:
                    reply.put(message)
            else:
                self._events.put(message)

    def _event_loop(self):
        while True:
            event = self._events.get()
            if event is None:
                return
            for method, session_id, callback in list(self._listeners):
                if method != event.get("method"):
                    continue
                if session_id is not None and session_id != event.get("sessionId"):
                    continue
                try:
                    callback(event.get("params", {}))
                except Exception as error:  # A failing callback must not stop event delivery.
                    print(f"CDP callback for {method} failed: {error}")

    def close(self):
        self._ws.close()
