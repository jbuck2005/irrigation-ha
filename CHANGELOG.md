# Changelog

## 1.0.6 - 2025-09-10
### Added
- Support for `ZONE=n TIME=0` in `irrigationd` to stop zones immediately.
- Home Assistant integration updated to send `TIME=0` when turning off zones.

### Fixed
- Zones can now be turned off early from the HA UI without waiting for timers.

