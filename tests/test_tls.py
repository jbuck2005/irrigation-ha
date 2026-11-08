"""Tests for TLS with the token as a pre-shared key, and the plain text fallback."""

import socket
import ssl
import threading
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.irrigation import status
from custom_components.irrigation.const import CONF_TLS, DOMAIN
from custom_components.irrigation.status import (
    NotTlsError,
    TlsRejectedError,
    psk_key,
    send_tls_command,
)

from .conftest import ENTRY_DATA, HOST, PORT, TOKEN

pytestmark = pytest.mark.skipif(not status.TLS_SUPPORTED, reason="needs Python 3.13 or later")


def test_psk_key_matches_irrigationd():
    """The key is SHA-256 of the label and the token, as irrigationd derives it."""
    # printf 'irrigationd-psk-v1:test-token' | sha256sum
    assert psk_key("test-token").hex() == (
        "3f63c084200c54bd2380f7365bce51dfc56dbd13dfa7cdee8340267cab5353b3"
    )


class TlsServer:
    """irrigationd's end of one connection over a socket pair, speaking TLS with a PSK.

    The test harness blocks network sockets, so `socket.create_connection` is
    patched to return the client end.
    """

    def __init__(self, token, reply=b"OK\n", plain_reply=None, cert=None):
        self.client, self.server = socket.socketpair()
        self.received = b""
        self.version = None
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        if cert is not None:
            # An impostor: no key, just a certificate of its own
            self.ctx.load_cert_chain(*cert)
        else:
            key = psk_key(token)
            self.ctx.set_psk_server_callback(lambda identity: key if identity == "irrigationd" else b"")
        self.reply = reply
        self.plain_reply = plain_reply
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def connect(self, address, timeout=None):
        self.client.settimeout(timeout)
        return self.client

    def _serve(self):
        try:
            if self.plain_reply is not None:
                # Like an irrigationd from before TLS: read a "line", answer in plain text
                self.received = self.server.recv(4096)
                self.server.sendall(self.plain_reply)
                return
            with self.ctx.wrap_socket(self.server, server_side=True) as conn:
                self.version = conn.version()
                while not self.received.endswith(b"\n"):
                    chunk = conn.recv(1024)
                    if not chunk:
                        break
                    self.received += chunk
                conn.sendall(self.reply)
        except (OSError, ssl.SSLError):
            pass
        finally:
            self.server.close()


def run_tls(server, token):
    with patch.object(status.socket, "create_connection", side_effect=server.connect):
        try:
            return send_tls_command(HOST, PORT, token, "STATUS")
        finally:
            server.thread.join(timeout=5)


def test_tls_round_trip():
    """A command goes over TLS 1.3, without the token in it."""
    server = TlsServer(TOKEN, reply=b"OK STATUS V=1 ZONES=1 Z1=OFF:0\n")
    assert run_tls(server, TOKEN) == "OK STATUS V=1 ZONES=1 Z1=OFF:0"
    assert server.version == "TLSv1.3"
    assert server.received == b"STATUS\n"


def test_tls_wrong_token_is_rejected():
    """A handshake with the wrong token fails, and nothing is sent."""
    server = TlsServer(TOKEN)
    with pytest.raises(TlsRejectedError):
        run_tls(server, "wrong-token")
    assert server.received == b""


def test_old_irrigationd_is_detected():
    """A plain text answer to the handshake means irrigationd is too old for TLS."""
    server = TlsServer(TOKEN, plain_reply=b"ERR auth required\n")
    with pytest.raises(NotTlsError):
        run_tls(server, TOKEN)
    # The handshake carries no token
    assert TOKEN.encode() not in server.received
    assert psk_key(TOKEN) not in server.received


def self_signed_cert(tmp_path):
    """Write a throwaway self-signed certificate and key, and return their paths."""
    from datetime import datetime, timedelta, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "impostor")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return str(cert_path), str(key_path)


def test_server_with_a_certificate_is_refused(tmp_path):
    """A server that skips the key and offers a certificate gets no command."""
    server = TlsServer(TOKEN, reply=b"OK\n", cert=self_signed_cert(tmp_path))
    with pytest.raises(TlsRejectedError, match="certificate"):
        run_tls(server, TOKEN)
    assert server.received == b""


def issue(hass, entry):
    return ir.async_get(hass).async_get_issue(DOMAIN, f"plain_token_{entry.entry_id}")


async def setup(hass, daemon, **data):
    entry = MockConfigEntry(domain=DOMAIN, title="Test Controller", data={**ENTRY_DATA, **data})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def poll(hass, entry):
    await hass.data[DOMAIN][entry.entry_id]["status"].async_poll()
    await hass.async_block_till_done()


async def test_new_irrigationd_uses_tls_and_remembers_it(hass, daemon):
    """The first poll goes over TLS, and the entry records it."""
    entry = await setup(hass, daemon)
    assert daemon.transports == ["tls"]
    assert entry.data[CONF_TLS] is True
    assert issue(hass, entry) is None


async def test_old_irrigationd_falls_back_to_plain_text(hass, daemon):
    """An irrigationd from before TLS still works, with a Repairs notice."""
    daemon.tls = False
    entry = await setup(hass, daemon)
    assert daemon.commands == [f"STATUS TOKEN={TOKEN}"]
    assert CONF_TLS not in entry.data
    assert issue(hass, entry).translation_key == "plain_token"
    assert hass.states.get("valve.irrigation_zone_1").state == "closed"

    # Valve commands work too
    await hass.services.async_call("valve", "open_valve", {"entity_id": "valve.irrigation_zone_1"}, blocking=True)
    assert daemon.commands[-1] == f"ZONE=1 TIME=300 TOKEN={TOKEN}"


async def test_tls_is_retried_hourly_not_every_poll(hass, daemon):
    """While irrigationd is old, TLS is tried again only after an hour."""
    daemon.tls = False
    with patch.object(status.time, "monotonic", return_value=1000.0):
        entry = await setup(hass, daemon)
        await poll(hass, entry)
    assert daemon.transports == ["plain", "plain"]

    # irrigationd is updated; an hour later the next poll finds TLS
    daemon.tls = True
    with patch.object(status.time, "monotonic", return_value=1000.0 + status.TLS_RETRY_INTERVAL):
        await poll(hass, entry)
    assert daemon.transports[-1] == "tls"
    assert entry.data[CONF_TLS] is True
    assert issue(hass, entry) is None


async def test_no_fallback_once_tls_has_worked(hass, daemon):
    """After TLS has worked, a plain text answer is an error and the token isn't sent."""
    entry = await setup(hass, daemon)
    daemon.tls = False
    sent = len(daemon.commands)

    # A valve command fails, instead of sending the token
    with pytest.raises(HomeAssistantError, match="didn't start"):
        await hass.services.async_call(
            "valve", "open_valve", {"entity_id": "valve.irrigation_zone_1"}, blocking=True
        )

    for _ in range(status.MAX_FAILED_POLLS):
        await poll(hass, entry)
    assert hass.states.get("valve.irrigation_zone_1").state == "unavailable"
    assert daemon.commands[sent:] == []
    assert daemon.transports.count("plain") == 0


async def test_tls_remembered_across_restarts(hass, daemon):
    """An entry that has used TLS never falls back, even right after setup."""
    daemon.tls = False
    entry = await setup(hass, daemon, **{CONF_TLS: True})
    assert daemon.commands == []
    assert issue(hass, entry) is None


async def test_wrong_token_never_falls_back(hass, daemon):
    """A refused TLS handshake doesn't make the integration try plain text."""
    entry = await setup(hass, daemon, token="wrong-token")
    assert daemon.commands == []
    assert CONF_TLS not in entry.data


async def test_old_python_uses_plain_text_with_its_own_notice(hass, daemon):
    """Without pre-shared key support in Python, plain text is used and explained."""
    with patch.object(status, "TLS_SUPPORTED", False):
        entry = await setup(hass, daemon)
    assert daemon.transports == ["plain"]
    assert issue(hass, entry).translation_key == "plain_token_old_python"


async def test_options_host_change_forgets_tls(hass, daemon):
    """A new host may be a different irrigationd, so TLS support is learned again."""
    entry = await setup(hass, daemon)
    assert entry.data[CONF_TLS] is True
    form = {"host": HOST, "port": PORT, "zones": 4, "default_duration": 300}

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch.object(hass.config_entries, "async_reload"):
        await hass.config_entries.options.async_configure(result["flow_id"], {**form, "token": "new-token-0123456789abcdef"})
    assert entry.data[CONF_TLS] is True

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch.object(hass.config_entries, "async_reload"):
        await hass.config_entries.options.async_configure(result["flow_id"], {**form, "host": "192.0.2.11"})
    assert CONF_TLS not in entry.data


async def test_plain_text_off_never_sends_the_token(hass, daemon):
    """With plain text turned off, an irrigationd without TLS gets nothing."""
    daemon.tls = False
    entry = await setup(hass, daemon, allow_plain_token=False)
    assert daemon.commands == []
    assert hass.states.get("valve.irrigation_zone_1").state == "closed"
    with pytest.raises(HomeAssistantError, match="didn't start"):
        await hass.services.async_call(
            "valve", "open_valve", {"entity_id": "valve.irrigation_zone_1"}, blocking=True
        )
    assert daemon.commands == []
    assert daemon.transports.count("plain") == 0
    assert CONF_TLS not in entry.data


async def test_plain_text_off_still_uses_tls(hass, daemon):
    """Turning plain text off doesn't stop TLS from working."""
    entry = await setup(hass, daemon, allow_plain_token=False)
    assert daemon.transports == ["tls"]
    assert entry.data[CONF_TLS] is True


def short_token_issue(hass, entry):
    return ir.async_get(hass).async_get_issue(DOMAIN, f"short_token_{entry.entry_id}")


async def test_short_stored_token_keeps_working_with_a_notice(hass, daemon):
    """A short token from before the minimum still works, and Repairs says so."""
    daemon.token = "short"
    entry = await setup(hass, daemon, token="short")
    assert entry.data["token"] == "short"
    assert daemon.transports == ["tls"]
    assert short_token_issue(hass, entry) is not None


async def test_long_token_has_no_notice(hass, daemon):
    entry = await setup(hass, daemon)
    assert short_token_issue(hass, entry) is None
