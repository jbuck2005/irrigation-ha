<p align="center">
  <img src="docs/banner.png" alt="irrigation-ha: local zone control for Home Assistant" width="100%">
</p>

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-0284C7.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![GitHub release (latest SemVer)](https://img.shields.io/github/v/release/jbuck2005/irrigation-ha)](https://github.com/jbuck2005/irrigation-ha/releases)
[![License](https://img.shields.io/github/license/jbuck2005/irrigation-ha)](./LICENSE)
![GitHub last commit](https://img.shields.io/github/last-commit/jbuck2005/irrigation-ha)
![GitHub Repo stars](https://img.shields.io/github/stars/jbuck2005/irrigation-ha?style=social)

# Irrigation Controller for Home Assistant

Custom integration that controls irrigation zones by talking to [`irrigationd`](https://github.com/jbuck2005/irrigationd) over your local network.  
Provides:
- An **Irrigation** sidebar panel and a dashboard card for controlling your zones
- **A valve for each zone**, grouped under a single device
- **A default run time for each zone**, with a number entity to change it
- Zone state read from `irrigationd`, so runs started elsewhere show up and survive a Home Assistant restart
- Host, port and token set in the UI, with the token matching `IRRIGATIOND_TOKEN` on the irrigationd host
- A bundled automation blueprint for watering zones one after another
- Sprinkler icons that change while a zone is running

### Requirements
- Home Assistant 2024.7 or later
- [`irrigationd`](https://github.com/jbuck2005/irrigationd) running and reachable from Home Assistant, with a token set and the `STATUS` command, which Home Assistant uses to read zone state
- Up to 14 zones per controller

---

## Installation

### Marketplace (Home Assistant 2026.11 and later)
HACS is built into Home Assistant as the Marketplace from 2026.11. This integration is not in the main catalog yet, so add it as a custom repository, which needs a GitHub connection:

1. Go to **Settings → Marketplace** and open **Custom repositories**.
2. Add this repo URL:  
   `https://github.com/jbuck2005/irrigation-ha`
3. Select category: **Integration**.
4. Install and restart Home Assistant.

### HACS (before 2026.11)
1. Go to **HACS → Integrations → Custom repositories**.
2. Add this repo URL:  
   `https://github.com/jbuck2005/irrigation-ha`
3. Select category: **Integration**.
4. Install and restart Home Assistant.

### Manual
1. Copy the `custom_components/irrigation` folder into  
   `/config/custom_components/irrigation/`
2. Restart Home Assistant.

---

## Configuration

After restart, add the integration from the UI:

**Settings → Devices & Services → Add Integration → Irrigation Controller**

You will be asked for:
- **Name** (default: Irrigation Controller)
- **Host**: the address of the irrigationd host, or `127.0.0.1` if it's on the same machine
- **Port** (default: 4242)
- **Number of zones** (default: 4, maximum: 14)
- **Default run time** (seconds, default: 300): the starting run time for every zone
- **Token**: the same value as `IRRIGATIOND_TOKEN` on the irrigationd host

These can be changed later under **Configure**, including the token. Leave the token blank to keep the current one.

### Configuring Individual Zone Durations

After initial setup, you can configure each zone's default duration in two ways:

#### Option 1: Device Page (Recommended)
1. Go to **Settings → Devices & Services → Irrigation Controller**
2. Click on your controller's device, which has the name you gave it at setup
3. You'll see `number.irrigation_zone_X_default_duration` entities for each zone
4. Adjust each zone's duration as needed (10 - 7200 seconds)

#### Option 2: Configure (Bulk Edit)
1. Go to **Settings → Devices & Services → Irrigation Controller**
2. Click **Configure**
3. You'll see individual run time fields for each zone, from 10 to 7200 seconds
4. Adjust all zones at once and click **Submit**
5. The integration will reload automatically with new settings

### Changing the token

Change `IRRIGATIOND_TOKEN` on the irrigationd host and restart `irrigationd`, then enter the same value under **Configure**. The token field is hidden and starts empty, and leaving it blank keeps the current token. Until both sides match, commands fail with `ERR token`.

---

## Irrigation panel

After setup, **Irrigation** appears in the sidebar, with nothing else to install or configure. It lists every zone, and from there you can:

- Start or stop a zone, and see the time left
- Change a zone's default run time, from 10 seconds to 2 hours
- Stop everything with **Stop all**, which shows while a zone is running

If a command fails, the zone shows a warning with the reason. A warning on a stopped zone means it may still be running, so check the controller.

`irrigationd` keeps a valve open for at most 2 hours in one go, and a zone that reaches that limit can't restart for 10 minutes unless it's stopped first. A run that would pass 2 hours is shortened to fit.

The integration checks the real zone state with `irrigationd` every 15 seconds, so runs started elsewhere show up and a running zone survives a Home Assistant restart. If it can't read the state for 45 seconds, the zones show as unavailable.

To rename a zone, rename its valve in Home Assistant and the panel follows.

### Dashboard card

To add the same controls to a dashboard, add the **Irrigation Zones** card, or use this YAML:

```yaml
type: custom:irrigation-zones-card
title: Irrigation
```

---

## Entities

A second controller adds its number after `irrigation`, such as `valve.irrigation_2_zone_1`.

### Valves
- `valve.irrigation_zone_X` → Zone valve for each irrigation zone, with the state `open` or `closed`
- Each valve has a `remaining` attribute showing countdown time
- Each valve has a `configured_duration` attribute showing the last run's duration
- Each valve has a `zone` attribute with its zone number

### Actions
- `valve.open_valve` runs a zone for its default run time
- `irrigation.run` runs one or more zones, with an optional `duration` from 10 to 7200 seconds
- `valve.close_valve` stops a zone early

If `irrigationd` refuses a command, the action fails with its reply, which stops an automation at that step. Add `continue_on_error: true` to a step that should carry on regardless. The blueprint already does this.

### Number Entities
- `number.irrigation_zone_X_default_duration` → Configure default run time for each zone individually
- Adjustable from 10 seconds to 2 hours (7200 seconds)
- Changes apply to the next run
- Persisted across Home Assistant restarts
- Accessible in Settings → Devices & Services → Irrigation Controller, on your controller's device

### Per-Zone Configuration Benefits
- **Different watering needs**: Set longer durations for lawn zones, shorter for drip irrigation
- **Seasonal adjustments**: Easily adjust individual zone times without reconfiguring the whole integration
- **Quick access**: Modify zone durations directly from the device page or entity cards
- **Automation friendly**: Use the number entities in automations to dynamically adjust watering schedules

---

## Building your own dashboard

The panel and the **Irrigation Zones** card cover most needs. To build your own view instead, start from this YAML for a **Manual card**:

```yaml
type: vertical-stack
cards:
  - type: entities
    title: Irrigation Zones
    entities:
      - entity: valve.irrigation_zone_1
        name: Front Lawn
      - entity: valve.irrigation_zone_2
        name: Back Lawn
      - entity: valve.irrigation_zone_3
        name: Garden Beds
  - type: history-graph
    title: Irrigation History
    entities:
      - entity: valve.irrigation_zone_1
      - entity: valve.irrigation_zone_2
      - entity: valve.irrigation_zone_3
    hours_to_show: 24
```

You can extend this with custom cards (e.g. `bar-card`) to show countdown timers
and progress bars per zone.

### Brand colours

An optional theme, [`docs/brand/irrigation-theme.yaml`](docs/brand/irrigation-theme.yaml), applies the project palette to your dashboards and adds `--irrigation-*` CSS variables for cards. See the [brand guide](docs/BRAND.md#lovelace-colours) for setup.

---

## Automation Blueprint

A ready-to-use blueprint is bundled in this repo:

📂 `blueprints/automation/irrigation/irrigation_cycle.yaml`

It runs zones one after another at a scheduled time. To import it, go to **Settings → Automations & scenes → Blueprints → Import blueprint** and paste this URL:

`https://github.com/jbuck2005/irrigation-ha/blob/main/blueprints/automation/irrigation/irrigation_cycle.yaml`

Then create an automation from **Irrigation Cycle**.

### Example setup

- Start Time: `06:00:00`
- Zones: select all your irrigation zone valves
- Durations: `300,600,300`

This will:
1. Run Zone 1 for 300s
2. Run Zone 2 for 600s
3. Run Zone 3 for 300s

Durations are comma-separated, in the same order as the zones. A zone with no duration runs for 300 seconds. If a zone is refused, the cycle moves on to the next one.

### YAML snippet

```yaml
use_blueprint:
  path: jbuck2005/irrigation_cycle.yaml
  input:
    start_time: "06:00:00"
    zones:
      entity_id:
        - valve.irrigation_zone_1
        - valve.irrigation_zone_2
        - valve.irrigation_zone_3
    durations: "300,600,300"
```

---

## Notes

- The integration sends commands straight to `irrigationd` over TCP.
- `irrigationd` limits failed token attempts. Set `IRRIGATIOND_TRUSTED_ADDR` on the irrigationd host to Home Assistant's address, so a flood of bad attempts can't block its commands.
- Logs can be checked via `Settings → System → Logs`. The token is never written to them.

---

## License

MIT © 2025–2026 jbuck2005
