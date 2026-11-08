"""Tests for the irrigationd connection: framing, limits, parsing and redaction."""

import socket
import threading
from unittest.mock import patch

import pytest

from custom_components.irrigation import status
from custom_components.irrigation.status import parse_status, safe_reply, send_command

class OneShotServer:
    """Stand in for irrigationd's end of one connection, answering with `behaviour`.

    The test harness blocks network sockets, so the connection is a local
    socket pair and `socket.create_connection` is patched to return our end.
    """

    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.client, self.server = socket.socketpair()
        self.port = 4242
        self.received = b""
        self.done = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def connect(self, address, timeout=None):
        assert address == ("192.0.2.10", self.port)
        self.client.settimeout(timeout)
        return self.client

    def _serve(self):
        conn = self.server
        with conn:
            while not self.received.endswith(b"\n"):
                chunk = conn.recv(1024)
                if not chunk:
                    break
                self.received += chunk
            try:
                self.behaviour(conn, self)
            except OSError:
                pass
        self.done.set()


@pytest.fixture
def serve():
    """Return a function that starts a fake irrigationd connection."""
    started = []

    def start(behaviour):
        server = OneShotServer(behaviour)
        started.append(server)
        return server

    with patch.object(status.socket, "create_connection", side_effect=lambda *a, **k: started[-1].connect(*a, **k)):
        yield start


def test_send_command_round_trip(serve):
    """A command goes out as one line and the reply comes back stripped."""
    server = serve(lambda conn, _: conn.sendall(b"OK\n"))
    assert send_command("192.0.2.10", server.port, "ZONE=1 TIME=30 TOKEN=t") == "OK"
    server.done.wait(2)
    assert server.received == b"ZONE=1 TIME=30 TOKEN=t\n"


def test_send_command_rejects_an_endless_reply(serve):
    """A peer that never sends a newline can't make the reply grow without limit."""

    def flood(conn, _):
        for _ in range(100):
            conn.sendall(b"x" * 1024)

    server = serve(flood)
    with pytest.raises(OSError, match="too long"):
        send_command("192.0.2.10", server.port, "STATUS TOKEN=t")


def test_send_command_has_a_total_deadline(serve):
    """A peer that sends one byte at a time can't hold the connection open forever."""
    stop = threading.Event()

    def drip(conn, _):
        while not stop.wait(0.2):
            conn.sendall(b"x")

    server = serve(drip)
    with patch.object(status, "COMMAND_DEADLINE", 1), pytest.raises(TimeoutError):
        send_command("192.0.2.10", server.port, "STATUS TOKEN=t")
    stop.set()


def test_send_command_survives_invalid_utf8(serve):
    """Bytes that aren't UTF-8 are replaced instead of raising."""
    server = serve(lambda conn, _: conn.sendall(b"ERR \xff\xfe\n"))
    reply = send_command("192.0.2.10", server.port, "STATUS TOKEN=t")
    assert reply.startswith("ERR ")


def test_parse_status():
    """A version 1 status line gives each zone's state and time left."""
    reply = "OK STATUS V=1 ZONES=3 Z1=OFF:0 Z2=ON:28 Z3=OFF:0 NEWFIELD=1"
    assert parse_status(reply) == {1: (False, 0), 2: (True, 28), 3: (False, 0)}


@pytest.mark.parametrize("reply", ["", "ERR invalid token", "OK STATUS V=2 Z1=ON:5"])
def test_parse_status_rejects_other_replies(reply):
    """Anything that isn't a version 1 status reply is refused."""
    assert parse_status(reply) is None


def test_safe_reply_hides_the_token():
    """A reply that echoes the command never puts the token in the log."""
    assert safe_reply("ERR bad ZONE=1 TIME=5 TOKEN=secret") == "ERR bad ZONE=1 TIME=5 TOKEN=***"


def test_safe_reply_strips_control_characters_and_shortens():
    """Control characters can't forge log lines, and long replies are cut."""
    assert safe_reply("ERR a\nFAKE LOG LINE") == "ERR a FAKE LOG LINE"
    assert len(safe_reply("x" * 1000)) == status.MAX_SHOWN_REPLY + 3
