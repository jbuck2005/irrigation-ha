# Changelog

## 1.2.1 - 2026-11-08
Initial release.

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
