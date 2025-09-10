# Irrigation Controller for Home Assistant (v1.0.4)

Custom integration to control irrigation zones through `irrigationd` + `irrigationctl`.  
Provides:
- Zone switches in Home Assistant
- Configurable default run time per zone
- Host/port configuration (no hardcoding required)
- A built-in automation blueprint for sequential irrigation cycles

---

## Installation

### HACS (recommended)
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
- **Zones** (default: 14)
- **Default duration** (seconds, default: 300)
- **Host** (default: 127.0.0.1)
- **Port** (default: 4242)

These can be changed later under **Configure → Options**.

---

## Entities

- `switch.irrigation_zone_X` → Zone switch for each irrigation zone.
- Turning on a switch runs the zone for the configured default duration (or a custom duration).
- Turning off a switch stops irrigation early.

---

## Lovelace Dashboard Example

You can visualize zone progress with bars. Example YAML for **Manual card**:

```yaml
type: vertical-stack
cards:
  - type: entities
    title: Irrigation Zones
    entities:
      - entity: switch.irrigation_zone_1
        name: Front Lawn
      - entity: switch.irrigation_zone_2
        name: Back Lawn
      - entity: switch.irrigation_zone_3
        name: Garden Beds
  - type: history-graph
    title: Irrigation History
    entities:
      - entity: switch.irrigation_zone_1
      - entity: switch.irrigation_zone_2
      - entity: switch.irrigation_zone_3
    hours_to_show: 24
    refresh_interval: 60
```

You can extend this with custom cards (e.g. `bar-card`) to show countdown timers
and progress bars per zone.

---

## Automation Blueprint

A ready-to-use blueprint is bundled in this repo:

📂 `blueprints/automation/irrigation/irrigation_cycle.yaml`

It allows you to run zones sequentially at a scheduled time.

### Example setup

- Start Time: `06:00:00`
- Zones: select all your irrigation zone switches
- Durations: `300,600,300`

This will:
1. Turn on Zone 1 for 300s
2. Turn on Zone 2 for 600s
3. Turn on Zone 3 for 300s

### YAML snippet

```yaml
use_blueprint:
  path: jbuck2005/irrigation-ha/irrigation_cycle.yaml
  input:
    start_time: "06:00:00"
    zones:
      entity_id:
        - switch.irrigation_zone_1
        - switch.irrigation_zone_2
        - switch.irrigation_zone_3
    durations: "300,600,300"
```

---

## Notes

- Requires `irrigationd` service running and accessible from HA.
- Uses `irrigationctl` under the hood.
- Logs can be checked via `Settings → System → Logs`.

---

## License

MIT © 2025 jbuck2005
