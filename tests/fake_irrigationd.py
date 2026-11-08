"""A stand-in for irrigationd that speaks its line protocol, for tests.

It never opens a real valve. Tests patch ``send_command`` (plain text) and
``send_tls_command`` to call ``FakeIrrigationd.handle_plain`` and
``handle_tls`` instead of opening a TCP connection.
"""

import re

from custom_components.irrigation.status import NotTlsError, TlsRejectedError

COMMAND = re.compile(r"^ZONE=(\d+) TIME=(\d+)(?: TOKEN=(\S+))?$")
STATUS = re.compile(r"^STATUS(?: TOKEN=(\S+))?$")
MAX_TIME = 7200


class FakeIrrigationd:
    """Keep zone state in memory and answer like irrigationd does."""

    def __init__(self, token="test-token", zones=14):
        """Start with every zone off."""
        self.token = token
        self.zones = {zone: 0 for zone in range(1, zones + 1)}
        self.commands = []
        # How each command arrived: "tls" or "plain"
        self.transports = []
        # False acts like an irrigationd from before TLS
        self.tls = True
        # False acts like IRRIGATIOND_PLAIN_TOKEN=no
        self.plain_allowed = True
        # Set to make the next replies fail: an exception to raise, or a reply string
        self.fail_with = None
        # Zones whose start commands are refused, like a zone at its maximum runtime
        self.refuse = set()

    def run(self, zone, seconds):
        """Start or stop a zone as if someone else had done it."""
        self.zones[zone] = seconds

    def handle_tls(self, token, command):
        """Answer a command sent over TLS keyed by `token`."""
        if not self.tls:
            raise NotTlsError("irrigationd doesn't support TLS yet")
        if token != self.token:
            raise TlsRejectedError("irrigationd refused the TLS handshake. Check the token")
        self.transports.append("tls")
        return self.handle(command, authenticated=True)

    def handle_plain(self, command):
        """Answer a command sent in plain text, with TOKEN= in it."""
        self.transports.append("plain")
        if self.tls and not self.plain_allowed:
            self.commands.append(command)
            return "ERR plain text disabled, use TLS"
        return self.handle(command)

    def handle(self, command, authenticated=False):
        """Return irrigationd's reply to one command line."""
        self.commands.append(command)
        if isinstance(self.fail_with, BaseException):
            raise self.fail_with
        if isinstance(self.fail_with, str):
            return self.fail_with

        if match := STATUS.match(command):
            if not authenticated and match[1] != self.token:
                return "ERR invalid token"
            fields = " ".join(
                f"Z{zone}={'ON' if left else 'OFF'}:{left}"
                for zone, left in self.zones.items()
            )
            return f"OK STATUS V=1 ZONES={len(self.zones)} {fields}"

        if match := COMMAND.match(command):
            zone, seconds, token = int(match[1]), int(match[2]), match[3]
            if not authenticated and token != self.token:
                return "ERR invalid token"
            if zone not in self.zones:
                return "ERR invalid zone"
            if seconds > MAX_TIME:
                return "ERR invalid time"
            if seconds and zone in self.refuse:
                return "ERR zone at maximum runtime"
            self.zones[zone] = seconds
            return "OK"

        return "ERR invalid command"

    def sent(self, prefix="ZONE="):
        """Return the zone commands sent so far, without the token."""
        return [c.rsplit(" TOKEN=", 1)[0] for c in self.commands if c.startswith(prefix)]
