"""
A small WebSocket client (RFC 6455), standard library only.

Just what talking to OBS's built-in server needs: a plain ws:// connection (OBS offers no TLS), text messages, ping/pong
and close. No compression, no extensions, client side only. Received bytes are buffered and only complete frames are
parsed, so a receive timeout can never leave a half-read frame behind.
"""

import base64
import hashlib
import os
import socket
import struct
import time

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_MESSAGE = 32 * 1024 * 1024          # far above anything OBS sends for our requests; protects memory from garbage


class WebSocketError(Exception):
    """The connection could not be set up or the peer broke the protocol."""


class ConnectionClosed(WebSocketError):
    def __init__(self, code=None, reason=""):
        self.code, self.reason = code, reason
        super().__init__(f"connection closed (code {code}{': ' + reason if reason else ''})")


def _mask(data, key):
    """XOR `data` with the repeating 4-byte `key` (fast for any size: one big-integer XOR)."""
    n = len(data)
    if not n:
        return b""
    stream = (key * (n // 4 + 1))[:n]
    return (int.from_bytes(data, "little") ^ int.from_bytes(stream, "little")).to_bytes(n, "little")


def accept_key(key):
    """The Sec-WebSocket-Accept value a server must answer for our Sec-WebSocket-Key."""
    return base64.b64encode(hashlib.sha1((key + _GUID).encode("ascii")).digest()).decode("ascii")


class WebSocket:
    def __init__(self, sock):
        self.sock = sock
        self.closed = False
        self._buf = bytearray()
        self._fragments = None                  # (opcode, bytearray) while a fragmented message arrives

    @classmethod
    def connect(cls, host, port, path="/", subprotocol=None, timeout=3.0):
        sock = socket.create_connection((host, port), timeout=timeout)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            host_header = f"[{host}]" if ":" in host else host
            lines = [f"GET {path} HTTP/1.1", f"Host: {host_header}:{port}", "Upgrade: websocket", "Connection: Upgrade",
                     f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
            if subprotocol:
                lines.append(f"Sec-WebSocket-Protocol: {subprotocol}")
            sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
            ws = cls(sock)
            status_line, headers = ws._read_http_head(timeout)
            parts = status_line.split(" ", 2)
            if len(parts) < 2 or parts[1] != "101":
                raise WebSocketError(f"not a WebSocket server (it answered: {status_line[:80]!r})")
            if headers.get("sec-websocket-accept") != accept_key(key):
                raise WebSocketError("the server's WebSocket handshake answer is wrong")
            return ws
        except BaseException:
            sock.close()
            raise

    def _read_http_head(self, timeout):
        deadline = time.monotonic() + timeout
        while b"\r\n\r\n" not in self._buf:
            if len(self._buf) > 65536:
                raise WebSocketError("handshake answer too long")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WebSocketError("no handshake answer")
            self.sock.settimeout(remaining)
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                raise WebSocketError("no handshake answer") from None
            if not chunk:
                raise WebSocketError("the server closed the connection during the handshake")
            self._buf += chunk
        end = self._buf.index(b"\r\n\r\n")
        head = bytes(self._buf[:end]).decode("latin-1")
        del self._buf[:end + 4]                 # anything after the head is already WebSocket data (kept)
        lines = head.split("\r\n")
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        return lines[0], headers

    # ---- sending
    def _send(self, opcode, payload):
        header = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        key = os.urandom(4)                     # clients must mask every frame
        self.sock.settimeout(5.0)
        try:
            self.sock.sendall(bytes(header) + key + _mask(payload, key))
        except OSError as error:
            self.closed = True
            raise ConnectionClosed(1006, f"send failed: {error}") from None

    def send_text(self, text):
        self._send(0x1, text.encode("utf-8"))

    # ---- receiving
    def _take_frame(self):
        buf = self._buf
        if len(buf) < 2:
            return None
        b0, b1 = buf[0], buf[1]
        if b0 & 0x70:
            raise WebSocketError("the server used a WebSocket extension we did not ask for")
        n, i = b1 & 0x7F, 2
        if n == 126:
            if len(buf) < 4:
                return None
            n, i = struct.unpack(">H", buf[2:4])[0], 4
        elif n == 127:
            if len(buf) < 10:
                return None
            n, i = struct.unpack(">Q", buf[2:10])[0], 10
        if n > MAX_MESSAGE:
            raise WebSocketError(f"message too large ({n} bytes)")
        key = None
        if b1 & 0x80:                           # servers must not mask, but accept it
            if len(buf) < i + 4:
                return None
            key, i = bytes(buf[i:i + 4]), i + 4
        if len(buf) < i + n:
            return None
        payload = bytes(buf[i:i + n])
        del buf[:i + n]
        return bool(b0 & 0x80), b0 & 0x0F, (_mask(payload, key) if key else payload)

    def _message(self, fin, opcode, payload):
        """-> a complete text (str) / binary (bytes) message, or None for control frames and unfinished fragments."""
        if opcode == 0x8:
            code = struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else 1005
            reason = payload[2:].decode("utf-8", errors="replace")
            try:
                self._send(0x8, payload[:2])
            except ConnectionClosed:
                pass
            self.closed = True
            raise ConnectionClosed(code, reason)
        if opcode == 0x9:
            self._send(0xA, payload)
            return None
        if opcode == 0xA:
            return None
        if opcode in (0x1, 0x2):
            if self._fragments is not None:
                raise WebSocketError("a new message started inside a fragmented one")
            if fin:
                return payload.decode("utf-8") if opcode == 0x1 else payload
            self._fragments = (opcode, bytearray(payload))
            return None
        if opcode == 0x0:
            if self._fragments is None:
                raise WebSocketError("continuation frame without a message")
            self._fragments[1].extend(payload)
            if len(self._fragments[1]) > MAX_MESSAGE:
                raise WebSocketError("message too large")
            if not fin:
                return None
            first, data = self._fragments
            self._fragments = None
            return bytes(data).decode("utf-8") if first == 0x1 else bytes(data)
        raise WebSocketError(f"unknown WebSocket frame type {opcode}")

    def recv(self, timeout):
        """The next message (str or bytes), or None if none arrived within `timeout` seconds. Raises ConnectionClosed."""
        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            frame = self._take_frame()
            if frame is not None:
                message = self._message(*frame)
                if message is not None:
                    return message
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self.sock.settimeout(remaining)
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                return None
            except OSError as error:
                self.closed = True
                raise ConnectionClosed(1006, str(error)) from None
            if not chunk:
                self.closed = True
                raise ConnectionClosed(1006, "connection lost")
            self._buf += chunk

    def close(self, code=1000):
        if not self.closed:
            try:
                self._send(0x8, struct.pack(">H", code))
            except (ConnectionClosed, OSError):
                pass
        self.closed = True
        try:
            self.sock.close()
        except OSError:
            pass
