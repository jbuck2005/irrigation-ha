"""Talk to irrigationd, and poll it for the state of each zone."""

from datetime import timedelta
import hashlib
import logging
import re
import socket
import ssl
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import CONF_TLS, DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

BUFFER_SIZE = 1024
# irrigationd's longest reply is 182 bytes, so anything far past that is wrong
MAX_REPLY_BYTES = 4096
# Seconds allowed for one whole exchange, not just each read
COMMAND_DEADLINE = 10
# Longest reply text shown in the log or the UI
MAX_SHOWN_REPLY = 200

STATUS_INTERVAL = timedelta(seconds=15)
MAX_FAILED_POLLS = 3
ZONE_FIELD = re.compile(r"Z(\d+)=(ON|OFF):(\d+)")


# TLS 1.3 with the token as a pre-shared key, as irrigationd's tls.h describes:
# the token itself never crosses the network. Python 3.13 (Home Assistant
# 2025.2) is the first with pre-shared keys in its ssl module.
PSK_LABEL = b"irrigationd-psk-v1:"
PSK_IDENTITY = "irrigationd"
TLS_SUITE = "TLS_AES_128_GCM_SHA256"
TLS_SUPPORTED = hasattr(ssl.SSLContext, "set_psk_client_callback")
# While irrigationd is too old for TLS, try it again this often, in seconds
TLS_RETRY_INTERVAL = 3600


class NotTlsError(OSError):
    """irrigationd answered without TLS, so it is a version from before TLS."""


class TlsRejectedError(OSError):
    """irrigationd refused the TLS handshake, most likely because the token is wrong."""


TOKEN_FIELD = re.compile(r"TOKEN=\S*")
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def send_command(host: str, port: int, command: str) -> str:
    """Send a command to irrigationd over TCP and return the response line.

    Raises OSError if the exchange takes longer than COMMAND_DEADLINE seconds
    in total, or the reply grows past MAX_REPLY_BYTES without a newline.
    """
    deadline = time.monotonic() + COMMAND_DEADLINE
    with socket.create_connection((host, port), timeout=5) as sock:
        return _exchange(sock, command, deadline)


def psk_key(token: str) -> bytes:
    """Return the pre-shared key irrigationd derives from the same token."""
    return hashlib.sha256(PSK_LABEL + token.encode("utf-8")).digest()


def _tls_context(token: str) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # The key proves who irrigationd is, so there is no certificate to check
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.maximum_version = ssl.TLSVersion.TLSv1_3
    key = psk_key(token)
    ctx.set_psk_client_callback(lambda _hint: (PSK_IDENTITY, key))
    return ctx


def send_tls_command(host: str, port: int, token: str, command: str) -> str:
    """Send a command over TLS keyed by the token, and return the response line.

    Raises NotTlsError if irrigationd answers without TLS, TlsRejectedError if
    it refuses the handshake, and OSError like send_command otherwise.
    """
    deadline = time.monotonic() + COMMAND_DEADLINE
    ctx = _tls_context(token)
    with socket.create_connection((host, port), timeout=5) as raw:
        raw.settimeout(max(0.1, min(5, deadline - time.monotonic())))
        try:
            sock = ctx.wrap_socket(raw)
        except ssl.SSLError as err:
            # An old irrigationd answers the handshake with a plain text line
            if err.reason == "WRONG_VERSION_NUMBER":
                raise NotTlsError("irrigationd doesn't support TLS yet") from None
            raise TlsRejectedError("irrigationd refused the TLS handshake. Check the token") from None
        with sock:
            if sock.version() != "TLSv1.3":
                raise TlsRejectedError("irrigationd didn't use TLS 1.3")
            return _exchange(sock, command, deadline)


def _exchange(sock, command: str, deadline: float) -> str:
    """Send one line on a connected socket and read one line back."""
    sock.sendall(command.encode("utf-8") + b"\n")
    data = b""
    while not data.endswith(b"\n"):
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("irrigationd took too long to reply")
        sock.settimeout(min(5, left))
        chunk = sock.recv(BUFFER_SIZE)
        if not chunk:
            break
        data += chunk
        if len(data) > MAX_REPLY_BYTES:
            raise OSError("irrigationd's reply is too long")
    return data.decode("utf-8", errors="replace").strip()


class IrrigationdClient:
    """Send one controller's commands, over TLS whenever irrigationd supports it.

    The token is only sent in plain text while this controller has never
    connected over TLS, so an older irrigationd keeps working. After the first
    TLS connection the entry remembers it, and a reply without TLS is an error
    from then on: someone blocking TLS gets nothing, not the token.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize the client."""
        self.hass = hass
        self._entry = entry
        self._host = entry.data.get("host", "127.0.0.1")
        self._port = entry.data.get("port", DEFAULT_PORT)
        self._token = entry.data.get("token") or ""
        # While irrigationd is too old for TLS, use plain text until this time
        self._plain_until = 0.0

    @property
    def _tls_confirmed(self) -> bool:
        return bool(self._entry.data.get(CONF_TLS))

    def _send(self, command: str) -> tuple[str, bool]:
        """Send a command without its token, and return (reply, whether TLS was used)."""
        if TLS_SUPPORTED and (self._tls_confirmed or time.monotonic() >= self._plain_until):
            try:
                return send_tls_command(self._host, self._port, self._token, command), True
            except NotTlsError:
                if self._tls_confirmed:
                    raise NotTlsError(
                        "irrigationd answered without TLS, though it used TLS before, "
                        "so the token was not sent"
                    ) from None
                self._plain_until = time.monotonic() + TLS_RETRY_INTERVAL
        elif self._tls_confirmed:
            raise OSError(
                "This Home Assistant can't use TLS, and irrigationd used it before, "
                "so the token was not sent"
            )
        return send_command(self._host, self._port, f"{command} TOKEN={self._token}"), False

    async def async_send(self, command: str) -> str:
        """Send a command, without its token, and return irrigationd's reply."""
        reply, used_tls = await self.hass.async_add_executor_job(self._send, command)
        self._note_transport(used_tls)
        return reply

    @callback
    def _note_transport(self, used_tls: bool):
        issue_id = f"plain_token_{self._entry.entry_id}"
        if used_tls:
            if not self._tls_confirmed:
                _LOGGER.info("irrigationd at %s now uses TLS; the token is no longer sent", self._entry.title)
                self.hass.config_entries.async_update_entry(
                    self._entry, data={**self._entry.data, CONF_TLS: True}
                )
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="plain_token" if TLS_SUPPORTED else "plain_token_old_python",
            translation_placeholders={"name": self._entry.title},
        )


def safe_reply(reply: str) -> str:
    """Return a reply that is safe to log or show: no token, no control characters, short."""
    reply = TOKEN_FIELD.sub("TOKEN=***", reply)
    reply = CONTROL_CHARS.sub(" ", reply)
    if len(reply) > MAX_SHOWN_REPLY:
        reply = reply[:MAX_SHOWN_REPLY] + "..."
    return reply


def parse_status(response: str):
    """Return {zone: (is_on, seconds)}, or None if this isn't a version 1 reply."""
    fields = response.split()
    if fields[:3] != ["OK", "STATUS", "V=1"]:
        return None
    zones = {}
    for field in fields[3:]:
        match = ZONE_FIELD.fullmatch(field)
        if match:
            zones[int(match[1])] = (match[2] == "ON", int(match[3]))
    return zones


class StatusPoller:
    """Keep one controller's valves in step with what irrigationd reports."""

    def __init__(self, hass: HomeAssistant, entry_id: str, client: IrrigationdClient):
        """Initialize the poller."""
        self.hass = hass
        self._entry_id = entry_id
        self._client = client
        self._failures = 0
        self.available = True

    @property
    def _entities(self):
        # A poll that finishes after its entry was unloaded has no one to tell
        return self.hass.data.get(DOMAIN, {}).get(self._entry_id, {}).get("entities", [])

    def _set_available(self, available: bool):
        if available != self.available:
            self.available = available
            for entity in self._entities:
                entity.async_write_ha_state()

    def _poll_failed(self, reason: str):
        self._failures += 1
        if self._failures == MAX_FAILED_POLLS:
            _LOGGER.warning("Can't read zone state from irrigationd: %s", safe_reply(reason))
            self._set_available(False)

    async def async_poll(self, _now=None):
        """Read every zone's state from irrigationd and apply it."""
        started = time.monotonic()
        try:
            response = await self._client.async_send("STATUS")
        except Exception as err:  # noqa: BLE001 - any failure is a failed poll
            self._poll_failed(str(err) or type(err).__name__)
            return

        zones = parse_status(response)
        if zones is None:
            self._poll_failed(response)
            return

        self._failures = 0
        self._set_available(True)
        for entity in self._entities:
            if entity._zone in zones:
                entity.apply_status(*zones[entity._zone], started)
