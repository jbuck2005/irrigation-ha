"""Shared fixtures for the irrigation tests."""

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.irrigation.const import DOMAIN

from .fake_irrigationd import FakeIrrigationd

# Documentation address (RFC 5737), never a real controller
HOST = "192.0.2.10"
PORT = 4242
TOKEN = "test-token"

ENTRY_DATA = {
    "name": "Test Controller",
    "host": HOST,
    "port": PORT,
    "zones": 4,
    "default_duration": 300,
    "zone_durations": {"1": 300, "2": 120, "3": 300, "4": 300},
    "token": TOKEN,
    "controller_number": 1,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load the integration from custom_components in every test."""
    yield


@pytest.fixture
def daemon():
    """Replace the TCP connection to irrigationd with a fake daemon."""
    fake = FakeIrrigationd(token=TOKEN)

    def send_plain(host, port, command):
        assert (host, port) == (HOST, PORT)
        return fake.handle_plain(command)

    def send_tls(host, port, token, command):
        assert (host, port) == (HOST, PORT)
        return fake.handle_tls(token, command)

    with (
        patch("custom_components.irrigation.status.send_command", side_effect=send_plain),
        patch("custom_components.irrigation.status.send_tls_command", side_effect=send_tls),
    ):
        yield fake


@pytest.fixture
def entry():
    """Return a config entry for one controller with four zones."""
    return MockConfigEntry(domain=DOMAIN, title="Test Controller", data=dict(ENTRY_DATA))


@pytest.fixture
async def loaded(hass, entry, daemon):
    """Set up the integration with the fake daemon, and return the entry."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
