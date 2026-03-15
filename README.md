# One2Track — Home Assistant Integration

[![Version](https://img.shields.io/badge/version-1.0.2-blue)](https://github.com/jurrienk/ha-one2track)

Custom Home Assistant integration for [One2Track](https://www.one2trackgps.com) GPS watches (children's and elderly trackers).

## Features

- **Device tracker** with GPS coordinates, zone detection, and address
- **14 sensors** — battery, SIM balance, signal strength, satellite count, speed, altitude, heading, GPS accuracy, steps, status, timestamps, phonebook contact count, and whitelist number count (last two are model-dependent)
- **Phonebook & whitelist sensors** — show contact/number count with full list as attributes (only created if the device supports these features)
- **Binary sensor** — fall detection
- **Buttons** — refresh location (activate GPS mode), find device (ring the watch)
- **Switch** — step counter toggle
- **Selects** — GPS tracking interval, profile/sound mode
- **19 services** — send message, force update, find device, intercom, set SOS number, set/add/remove phonebook contacts, set/add/remove whitelist numbers, set alarms, set quiet times, set language/timezone, change password, factory reset, remote shutdown, and a raw diagnostics service
- **Multi-model support** — automatically discovers each watch's capabilities (Connect MOVE, Connect UP, and others)
- **Device targeting** — all services support `entity_id`, `device_id`, and `area_id` targeting
- **Persistent settings** — phonebook, whitelist, alarms, and quiet times survive HA restarts

## Installation

### HACS (recommended)

1. Open HACS in your Home Assistant instance
2. Go to **Integrations** and click the three-dot menu in the top right
3. Select **Custom repositories**
4. Add `https://github.com/jurrienk/ha-one2track` with category **Integration**
5. Search for "One2Track" and install it
6. Restart Home Assistant
7. Go to **Settings > Devices & Services > Add Integration** and search for **One2Track**
8. Enter your One2Track portal username and password

### Manual

1. Copy the `custom_components/one2track` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant
3. Add the integration via **Settings > Devices & Services**

## Supported Devices

The integration auto-discovers your watches and their capabilities. Tested with:

- **Connect UP** (model_id 77) — GPS interval code 0077, step counter code 0082
- **Connect MOVE** (model_id 27) — GPS interval code 0078, step counter code 0079, plus whitelist, intercom, and password change

Other One2Track watch models should work — the integration discovers available commands dynamically rather than hardcoding per model.

## How It Works

There is no official One2Track API. This integration communicates with `www.one2trackgps.com` (a Ruby on Rails web application) by:

1. Authenticating via the login form with session cookies and CSRF tokens
2. Polling device state by scraping inline JavaScript variables from device pages
3. Refreshing base data from the JSON device list endpoint
4. Sending commands via form POSTs that mimic the web portal's PATCH requests

## Diagnostics

Call the `one2track.get_raw_device_data` service to get raw data from all sources (JSON API, HTML scraping, coordinator state, discovered capabilities). This is invaluable for debugging data issues.

## Documentation

See [TESTING.md](TESTING.md) for the full architecture reference, entity specifications, service examples, and test procedures.

## Changelog

### v1.0.2 (2026-03-15)

- **Docs:** Aligned version numbers across all documentation (README, TESTING.md, manifest)
- **Docs:** Added privacy guidelines to CLAUDE.md to prevent leaking private device/entity information

### v1.0.1 (2026-03-15)

- **Docs:** Removed personal name references from documentation

### v1.0.0 (2026-03-15)

- **Fix:** Alarm values synced from portal are now validated — malformed values (e.g. JavaScript template fragments) are discarded and local state is preserved
- **Fix:** `add_phonebook_contact` no longer raises a false error when the portal returns HTTP 500 on a successful write — local state is updated optimistically
- **Fix:** All service validation errors now use `ServiceValidationError` for proper HA UI error display instead of raw 500 messages
- **Fix:** `intercom` and `change_password` capability errors now show the device name and a clear message about Connect MOVE requirement
- **Fix:** `alarms` and `quiet_times` attributes are always present on the device tracker (empty list `[]` when cleared, instead of disappearing)
- **Fix:** Test plan device model labels corrected to match device models (Connect UP, Connect MOVE)
- **Improvement:** Heading sensor satellite_count comparison is now type-safe
- **Improvement:** Whitelist full error message now suggests using `set_whitelist` as an alternative

### v0.9.9

- Individual phonebook/whitelist management (add/remove contacts and numbers)
- Portal readback before modify operations
- Persistent settings storage across HA restarts
- 19 services with full entity/device/area targeting
