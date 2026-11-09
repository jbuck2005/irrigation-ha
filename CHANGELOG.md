# Changelog

## Unreleased

## 1.3.2 - 2026-11-09

- **Stopping a zone that's about to start keeps it closed.** Pressed in the pause before the zone opens, or while the master valve opens ahead of it, Stop used to let it open anyway and run its full time. Starting such a zone again no longer queues a second run, and the panel shows it as waiting
- Removing, disabling or reloading a controller while its first zone waits for the master valve no longer leaves the master zone open for that zone's run time

## 1.3.1 - 2026-11-09

- **Plain text is off for new controllers.** A new option, **Allow the token in plain text**, is needed before the token is ever sent unencrypted to an `irrigationd` too old for TLS. Existing controllers keep their current behaviour, and it can be changed under **Configure**
- A newly entered token must be at least 16 characters. A shorter token that is already stored keeps working, and Repairs shows a notice suggesting a new one
- If the master switch fails to turn on after a master zone opened, the master zone is closed again, and an unexpected error starting a queued zone skips only that zone
- **Stop all now stops a zone that's about to start.** Pressed in the pause between zones or during the master lead time, it used to let the next zone open and run its full time. It also no longer waits for that run, and `irrigation.stop_all` stops every controller at once
- Starting a zone that's already running does nothing, instead of queueing a second full run
- If a start's reply is lost, the zone and master zone are sent a stop, so nothing is left open without Home Assistant knowing
- A busy `irrigationd` (too many connections open, or rate limiting) is no longer mistaken for one too old for TLS, so it never leads to the token being sent in plain text
- A program's start time runs once even when clocks go back and the hour repeats, and a start time in the hour skipped when clocks go forward now runs at the end of that gap instead of not at all

The matching `irrigationd` security fixes are in [its changelog](https://github.com/jbuck2005/irrigationd/blob/main/CHANGELOG.md).

## 1.3.0 - 2026-11-08

### Before you update

- Needs Home Assistant 2025.3 or later
- **Zones now run one at a time.** Starting a zone while another runs puts it in a queue, and it starts when the zones ahead of it finish. Closing the running zone starts the next one; closing a waiting zone cancels it
- Reloading a controller, such as after saving **Configure**, now closes its zones
- The valve's `configured_duration` attribute is now the zone's default run time; the length of the current or last run is in `run_duration`

### New

- **Programs.** Add them with **Add program** on the controller's integration page. Each has up to four start times a day, runs every day, on chosen weekdays, every few days, or on odd or even dates, and waters its zones in order through the run queue
- Each program is a device with a schedule switch, a **Run now** button, and next and last run sensors. `irrigation.run_program` runs one now. Starting a program that is already running is refused, so a double tap waters once
- If Home Assistant restarts while a program runs, its remaining zones are skipped and a notification says so
- **Stop all** and **Skip zone** buttons for each controller, and an `irrigation.stop_all` action. The panel's **Stop all** now clears the queue too
- Status and queued-runs sensors for each controller
- An optional master valve or pump: a zone, or a Home Assistant switch, that opens before each zone and closes after it, with a lead time of up to 10 seconds. Set it under **Configure**

### Security

- Over TLS, a server that offers a certificate instead of using the token is refused, so a device pretending to be `irrigationd` can't fake its replies
- Commands go over TLS 1.3 with the token as the key when `irrigationd` supports it, so the token no longer crosses the network. An older `irrigationd` still works, with a Repairs notice, and once TLS has worked with a controller the token is never sent to it in plain text again
- A master switch, such as a pump, is turned off when the controller starts (or as soon as the switch becomes available), so a pump left on by a crash doesn't keep running against closed valves. If turning it off fails, Repairs shows a notice
- The token is removed from anything logged or shown in an error
- A reply from `irrigationd` is limited to 4 KB and 10 seconds, so a wrong host can't stall Home Assistant
- Setup and **Configure** check the default run time (10 seconds to 2 hours) and the port, and refuse a host or token containing spaces or control characters

### Fixes and other changes

- README: run queue and master valve sections, screenshots, troubleshooting, updating/removing and security sections; blueprint durations hint fixed
- The integration is listed under the **Garden & plants** category in Home Assistant
- Any failed status read now counts toward marking zones unavailable
- A long run no longer holds up Home Assistant's startup or reloads
- A local test suite in `tests/`, run with `pytest`

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
