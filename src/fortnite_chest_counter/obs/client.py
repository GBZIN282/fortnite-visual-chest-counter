"""
OBS Studio's built-in WebSocket server (obs-websocket 5.x, part of OBS 28 and newer): connect, log in, and the few
requests this app needs.

A logged-in client could control all of OBS. This one only ever sends the request types in ALLOWED_REQUESTS: it lists
inputs, reads one input's settings and sets the text of the Text source the user picked (and, only when the user clicks
"Use direct updates", switches that source's "Read from file" off). Protocol reference:
https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md
"""

import base64
import hashlib
import itertools
import json

from fortnite_chest_counter.obs.websocket import ConnectionClosed, WebSocket, WebSocketError

RPC_VERSION = 1
SUBSCRIBE_GENERAL = 1 << 0               # ExitStarted
SUBSCRIBE_INPUTS = 1 << 3                # InputCreated / InputRemoved / InputNameChanged / InputSettingsChanged
ALLOWED_REQUESTS = frozenset({"GetVersion", "GetInputList", "GetInputSettings", "SetInputSettings"})
# Text source kinds (unversioned ids) -> (their "read from file" setting, their file path setting).
TEXT_KINDS = {"text_gdiplus": ("read_from_file", "file"), "text_ft2_source": ("from_file", "text_file")}
RESOURCE_NOT_FOUND = 600

CLOSE_AUTH_FAILED, CLOSE_UNSUPPORTED_RPC, CLOSE_KICKED = 4009, 4010, 4011


class ObsError(Exception):
    """Something the user can act on; str() is a plain sentence."""


class ObsUnavailable(ObsError):
    """OBS (or its WebSocket server) cannot be reached right now - worth trying again later."""


class ObsDisconnected(ObsError):
    """An established connection ended (OBS closed, network lost) - worth trying again later."""


class ObsAuthFailed(ObsError):
    """Wrong or missing password - trying again will not help until the user changes it."""


class ObsKicked(ObsError):
    """Disconnected from OBS's side ("Kick" in the WebSocket settings) - the protocol says: do not reconnect by itself."""


class ObsUnsupported(ObsError):
    """Not an obs-websocket 5 server (OBS older than 28, or another program on that port)."""


class ObsRequestFailed(ObsError):
    def __init__(self, request_type, code, comment):
        self.request_type, self.code, self.comment = request_type, code, comment
        super().__init__(f"OBS refused {request_type} ({code}{': ' + comment if comment else ''})")


def auth_string(password, salt, challenge):
    """obs-websocket 5 login: base64(sha256(base64(sha256(password + salt)) + challenge))."""
    secret = base64.b64encode(hashlib.sha256((password + salt).encode("utf-8")).digest()).decode("ascii")
    return base64.b64encode(hashlib.sha256((secret + challenge).encode("utf-8")).digest()).decode("ascii")


def _closed_error(error):
    if error.code == CLOSE_AUTH_FAILED:
        return ObsAuthFailed("OBS did not accept the password. Copy it again from OBS: Tools > WebSocket Server "
                             "Settings > Show Connect Info.")
    if error.code == CLOSE_UNSUPPORTED_RPC:
        return ObsUnsupported("This OBS WebSocket version is not supported. Update OBS Studio (28 or newer).")
    if error.code == CLOSE_KICKED:
        return ObsKicked("OBS disconnected the app (Kick in OBS's WebSocket settings). Click Connect to connect again.")
    return ObsDisconnected("The connection to OBS was lost" + (f" ({error.reason})" if error.reason else "") + ".")


class ObsClient:
    def __init__(self, host, port, password="", timeout=3.0, subscriptions=SUBSCRIBE_GENERAL | SUBSCRIBE_INPUTS):
        self.host, self.port, self.password, self.timeout = host, int(port), password or "", timeout
        self.subscriptions = subscriptions
        self.ws = None
        self.obs_version = self.websocket_version = None
        self.events = []                                # events that arrived while waiting for a response
        self._ids = itertools.count(1)

    # ---- connection
    def connect(self):
        try:
            self.ws = WebSocket.connect(self.host, self.port, subprotocol="obswebsocket.json", timeout=self.timeout)
        except OSError as error:
            raise ObsUnavailable(f"OBS is not reachable at {self.host}:{self.port} - is OBS open, with "
                                 f"Tools > WebSocket Server Settings > Enable WebSocket server ticked? ({error})") from None
        except WebSocketError as error:
            raise ObsUnsupported(f"{self.host}:{self.port} is not OBS's WebSocket server ({error}).") from None
        hello = self._expect(0, "OBS sent no greeting - is this OBS Studio 28 or newer, and the right port?")
        data = hello.get("d", {})
        self.obs_version, self.websocket_version = data.get("obsStudioVersion"), data.get("obsWebSocketVersion")
        identify = {"rpcVersion": RPC_VERSION, "eventSubscriptions": self.subscriptions}
        auth = data.get("authentication")
        if auth:
            if not self.password:
                raise ObsAuthFailed("OBS asks for a password. Copy it from OBS: Tools > WebSocket Server Settings > "
                                    "Show Connect Info.")
            identify["authentication"] = auth_string(self.password, auth.get("salt", ""), auth.get("challenge", ""))
        self._send(1, identify)
        self._expect(2, "OBS did not confirm the login.")
        if not self.obs_version:                        # older 5.x servers do not say it in the greeting
            try:
                info = self.request("GetVersion")
                self.obs_version, self.websocket_version = info.get("obsVersion"), info.get("obsWebSocketVersion")
            except ObsError:
                pass
        return self

    def close(self):
        if self.ws is not None:
            self.ws.close()
            self.ws = None

    @property
    def version_text(self):
        parts = [f"OBS {self.obs_version}" if self.obs_version else "OBS",
                 f"WebSocket {self.websocket_version}" if self.websocket_version else None]
        return ", ".join(p for p in parts if p)

    # ---- messages
    def _send(self, op, data):
        try:
            self.ws.send_text(json.dumps({"op": op, "d": data}))
        except ConnectionClosed as error:
            raise _closed_error(error) from None

    def _receive(self, timeout):
        """-> one decoded message dict, or None after `timeout` s."""
        try:
            raw = self.ws.recv(timeout)
        except ConnectionClosed as error:
            raise _closed_error(error) from None
        except (WebSocketError, OSError) as error:
            raise ObsDisconnected(f"The connection to OBS broke ({error}).") from None
        if raw is None:
            return None
        try:
            message = json.loads(raw)
        except (TypeError, ValueError):
            raise ObsUnsupported("OBS sent something that is not obs-websocket JSON.") from None
        return message if isinstance(message, dict) else None

    def _expect(self, op, problem):
        while True:
            message = self._receive(self.timeout)
            if message is None:
                raise ObsUnsupported(problem)
            if message.get("op") == op:
                return message
            if message.get("op") == 5:
                self.events.append(message.get("d", {}))

    def request(self, request_type, data=None, timeout=None):
        if request_type not in ALLOWED_REQUESTS:
            raise ValueError(f"{request_type} is not a request this app sends")
        request_id = str(next(self._ids))
        payload = {"requestType": request_type, "requestId": request_id}
        if data:
            payload["requestData"] = data
        self._send(6, payload)
        while True:
            message = self._receive(self.timeout if timeout is None else timeout)
            if message is None:
                raise ObsDisconnected(f"OBS did not answer ({request_type}).")
            d = message.get("d", {})
            if message.get("op") == 5:
                self.events.append(d)
            elif message.get("op") == 7 and d.get("requestId") == request_id:
                status = d.get("requestStatus", {})
                if not status.get("result"):
                    raise ObsRequestFailed(request_type, status.get("code"), status.get("comment", ""))
                return d.get("responseData") or {}

    def poll(self, timeout):
        """Events that arrived within `timeout` seconds (also those queued while waiting for responses)."""
        events, self.events = self.events, []
        message = self._receive(timeout)
        while message is not None:
            if message.get("op") == 5:
                events.append(message.get("d", {}))
            message = self._receive(0)
        return events


# ==================================================================
# Text sources
# ==================================================================

def text_kind(input_kind, unversioned=None):
    """'text_gdiplus' | 'text_ft2_source' | None. OBS reports versioned kinds like 'text_gdiplus_v3'."""
    for kind in TEXT_KINDS:
        if unversioned == kind or (input_kind or "") == kind or (input_kind or "").startswith(kind + "_v"):
            return kind
    return None


def list_text_sources(client):
    """-> [{"name", "uuid", "kind"}] for every Text (GDI+) / Text (FreeType 2) source, sorted by name."""
    inputs = client.request("GetInputList").get("inputs", [])
    out = []
    for item in inputs:
        kind = text_kind(item.get("inputKind"), item.get("unversionedInputKind"))
        if kind and item.get("inputName"):
            out.append({"name": item["inputName"], "uuid": item.get("inputUuid") or "", "kind": kind})
    return sorted(out, key=lambda s: s["name"].lower())


def find_source(sources, name="", uuid=""):
    """The saved source among `sources`: by OBS id first (survives a rename), else by name."""
    if uuid:
        for s in sources:
            if s["uuid"] == uuid:
                return s
    for s in sources:
        if name and s["name"] == name:
            return s
    return None


def _ref(source):
    return {"inputUuid": source["uuid"]} if source.get("uuid") else {"inputName": source["name"]}


def reads_file(client, source):
    """-> (True/False, the file it reads or "") - with "Read from file" on, OBS ignores the source's text setting."""
    settings = client.request("GetInputSettings", _ref(source)).get("inputSettings", {})
    use_key, file_key = TEXT_KINDS[source["kind"]]
    return bool(settings.get(use_key, False)), str(settings.get(file_key, "") or "")


def set_text(client, source, text):
    """Only the text changes; font, colour, size and every other setting of the source stay as they are."""
    client.request("SetInputSettings", {**_ref(source), "inputSettings": {"text": text}, "overlay": True})


def use_direct_updates(client, source, text):
    """Untick "Read from file" on this source and give it the current text (only on the user's explicit click)."""
    use_key, _ = TEXT_KINDS[source["kind"]]
    client.request("SetInputSettings", {**_ref(source), "inputSettings": {use_key: False, "text": text}, "overlay": True})
