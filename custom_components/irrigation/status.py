"""Talk to irrigationd, and poll it for the state of each zone."""

from datetime import timedelta
import logging
import re
import socket
import time

from homeassistant.core import HomeAssistant

from .const import DOMAIN

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


TOKEN_FIELD = re.compile(r"TOKEN=\S*")
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def send_command(host: str, port: int, command: str) -> str:
    """Send a command to irrigationd over TCP and return the response line.

    Raises OSError if the exchange takes longer than COMMAND_DEADLINE seconds
    in total, or the reply grows past MAX_REPLY_BYTES without a newline.
    """
    deadline = time.monotonic() + COMMAND_DEADLINE
    with socket.create_connection((host, port), timeout=5) as sock:
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

    def __init__(self, hass: HomeAssistant, entry_id: str, host: str, port: int, token: str):
        """Initialize the poller."""
        self.hass = hass
        self._entry_id = entry_id
        self._host = host
        self._port = port
        self._token = token
        self._failures = 0
        self.available = True

    @property
    def _entities(self):
        return self.hass.data[DOMAIN][self._entry_id]["entities"]

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
            response = await self.hass.async_add_executor_job(
                send_command, self._host, self._port, f"STATUS TOKEN={self._token}"
            )
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
