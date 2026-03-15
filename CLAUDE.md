# CLAUDE.md — One2Track Integration

## What This Is

A custom Home Assistant integration for One2Track GPS watches (children/elderly trackers). Domain: `one2track`. There is no official API — the integration scrapes `www.one2trackgps.com` (a Ruby on Rails app) using session cookies, CSRF tokens, and HTML parsing.

## Key Files

- `custom_components/one2track/api.py` — All HTTP communication (auth, scraping, commands, capability discovery)
- `custom_components/one2track/coordinator.py` — DataUpdateCoordinator, merges JSON + HTML data, stores per-device capabilities
- `custom_components/one2track/services.py` — All HA service handlers and registration
- `custom_components/one2track/entity.py` — Base entity class (shared device_info, data access)
- `custom_components/one2track/const.py` — Command codes, URLs, constants
- `custom_components/one2track/sensor.py` — 12 standard + 2 conditional sensor entities (phonebook, whitelist)
- `custom_components/one2track/device_tracker.py` — GPS tracker entity with attributes
- `custom_components/one2track/switch.py` — Step counter toggle (model-aware: 0079 or 0082)
- `custom_components/one2track/select.py` — GPS interval + profile mode selectors (dynamically discovered)
- `custom_components/one2track/button.py` — Refresh location + find device buttons
- `custom_components/one2track/binary_sensor.py` — Fall detection
- `TESTING.md` — Full architecture, entity reference, service examples, test procedures

## Critical Implementation Details

These have caused regressions before — do not change without understanding:

1. **Command format is PATCH (Rails convention):**
   - URL: `POST /devices/{uuid}/functions` (NOT `/api/devices/...`)
   - Body must include `_method=patch`, `authenticity_token`, `function[cmd_code]`, `function[cmd_value][]` (repeated for each value)
   - Header `x-csrf-token` required

2. **Cookie name:** The server may use `_iadmin` or `_session_id`. The client auto-detects which one the server sends. Both are checked in `_parse_cookie`.

3. **Session must be dedicated:** Use `async_create_clientsession(hass)` not `async_get_clientsession(hass)` — shared session causes auth failures.

4. **Account ID extraction:** The login redirect URL is absolute (`https://www.one2trackgps.com/users/12345/devices`), parse with `urlparse` — don't naively split on `/`.

5. **`balance_cents` API field contains cents.** Divide by 100 to get euros. The attribute is named `balance_eur`.

6. **Services must accept `device_id`, `entity_id`, and `area_id`** — HA's automation editor defaults to device_id targeting.

7. **Multi-model support is critical.** Different watch models (Connect MOVE model_id=27, Connect UP model_id=77) support different commands:
   - GPS interval: MOVE uses cmd 0078, UP uses 0077
   - Step counter: MOVE uses 0079, UP uses 0082
   - Whitelist, intercom, change password: MOVE only
   - The integration discovers capabilities at init via `GET /devices/{uuid}/functions?list_only=true`
   - Option values for selects are discovered via `GET /devices/{uuid}/functions?function={code}&list_only=true&modal=true`
   - **Never hardcode command codes or option values per model** — always use discovered capabilities

## Privacy

Never include private or personally identifiable information in documentation, code comments, or commit messages. This includes:

- Real device names, watch names, or personal names
- Real phone numbers, SIM numbers, or serial numbers
- Real entity IDs, device IDs, UUIDs, or account IDs from test devices
- Real addresses, coordinates, or location data

Always use generic placeholders (e.g. `<device_id>`, `0031612345678`, `device_tracker.my_watch`, `12345`) in examples and documentation.

## Version Bumping

Always bump the version in `manifest.json` when making changes.

## Testing

Read `TESTING.md` for the complete reference. Key diagnostic tool: the `one2track.get_raw_device_data` service returns raw data from all sources (JSON API, HTML scraping, coordinator state, discovered capabilities) for comparison.

## No Tests / No CI

This repo has no automated tests or CI pipeline. Changes are validated via manual testing on a live HA instance with real One2Track devices.
