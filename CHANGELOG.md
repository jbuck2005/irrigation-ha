# Changelog

## Unreleased

- Commands go over TLS 1.3 with the token as the key when `irrigationd` supports it, so the token no longer crosses the network. An older `irrigationd` still works, with a Repairs notice, and once TLS has worked with a controller the token is never sent to it in plain text again
- README: screenshots, troubleshooting, updating/removing and security sections; blueprint durations hint fixed
- The integration is listed under the **Garden & plants** category in Home Assistant
- Setup and **Configure** check the default run time (10 seconds to 2 hours) and the port, and refuse a host or token containing spaces or control characters
- A reply from `irrigationd` is limited to 4 KB and 10 seconds, so a wrong host can't stall Home Assistant
- The token is removed from anything logged or shown in an error
- Any failed status read now counts toward marking zones unavailable
- A long run no longer holds up Home Assistant's startup or reloads
- A local test suite in `tests/`, run with `pytest`
- **Zones now run one at a time.** Starting a zone while another runs puts it in a queue, and it starts when the zones ahead of it finish. Closing the running zone starts the next one; closing a waiting zone cancels it
- **Stop all** and **Skip zone** buttons for each controller, and an `irrigation.stop_all` action. The panel's **Stop all** now clears the queue too
- Status and queued-runs sensors for each controller
- An optional master valve or pump: a zone, or a Home Assistant switch, that opens before each zone and closes after it, with a lead time of up to 10 seconds. Set it under **Configure**
- Reloading a controller, such as after saving **Configure**, now closes its zones
- The valve's `configured_duration` attribute is now the zone's default run time; the length of the current or last run is in `run_duration`
- **Programs.** Add them with **Add program** on the controller's integration page. Each has up to four start times a day, runs every day, on chosen weekdays, every few days, or on odd or even dates, and waters its zones in order through the run queue
- Each program is a device with a schedule switch, a **Run now** button, and next and last run sensors. `irrigation.run_program` runs one now
- If Home Assistant restarts while a program runs, its remaining zones are skipped and a notification says so
- Needs Home Assistant 2025.3 or later

## 1.2.1 - 2026-11-08
First public release. Earlier versions were private and aren't listed here.

- An **Irrigation** sidebar panel and an **Irrigation Zones** dashboard card for starting and stopping zones, with the time left and a **Stop all** button
- A `valve` entity for each zone, such as `valve.irrigation_zone_1`, grouped under a device named after the controller
- A default run time for each zone, from 10 seconds to 2 hours, set with a number entity, from the panel or under **Configure**
- `irrigation.run`, which runs one or more zones for an optional duration
- Zone state read from `irrigationd` every 15 seconds, so runs started elsewhere show up and a run survives a Home Assistant restart. Zones become unavailable when `irrigationd` can't be reached for 45 seconds
- A refused or failed command fails the action with `irrigationd`'s reply, and the panel shows the reason
- More than one controller, with IDs such as `valve.irrigation_2_zone_1`
- Host, port, zones, run times and token can all be changed under **Configure**. The token field is hidden, and leaving it blank keeps the current token
- An automation blueprint that runs zones one after another at a set time, and carries on past a refused zone
- An optional dashboard theme with the project colours
