# One2Track Integration — Testing & Architecture Reference

> **Version:** 1.0.2
> **Integration domain:** `one2track`
> **Source:** `custom_components/one2track/`

This document is the single reference for testing the One2Track custom integration for Home Assistant. It covers architecture, data flow, multi-model support, all entities, all services, known limitations, and test procedures.

---

## 1. Architecture Overview

The integration communicates with `www.one2trackgps.com` (a Ruby on Rails app) — there is no official API. It uses session-based web authentication (cookies + CSRF tokens) and three data sources:

### Data Sources

| Source | URL pattern | Returns | Used for |
|--------|------------|---------|----------|
| **JSON API** | `GET /users/{account_id}/devices` | Array of `{device: {...}}` objects | Initial device discovery (uuid, name, serial, simcard, phone_number, status) |
| **HTML scraping** | `GET /devices/{uuid}` | HTML page with embedded `var device = {...}` and `var last_location = {...}` JS vars | Periodic state updates (battery, location, signal, speed, etc.) |
| **Capability discovery** | `GET /devices/{uuid}/functions?list_only=true` | HTML page with function links | Discover which commands each device supports |

### Data Flow

```
Login → GET /auth/users/sign_in (get CSRF + cookie)
      → POST /auth/users/sign_in (authenticate)
      → GET / (redirect reveals account_id)

Discovery → GET /users/{account_id}/devices (JSON)
          → Returns list of devices with uuid, name, serial_number, simcard, status

Capability Discovery (per device, at init only):
  → GET /devices/{uuid}/functions?list_only=true
  → Parse <a href="...?function=XXXX"> links → supported command list
  → For radio-option commands (GPS interval, profile mode):
    → GET /devices/{uuid}/functions?function={code}&list_only=true&modal=true
    → Parse <input type="radio"> + <label> → option values & current selection

Polling (every 60s) → For each device UUID:
                     → GET /devices/{uuid} (HTML page)
                     → Parse "var device = {...}" and "var last_location = {...}"
                     → Merge with discovery data

Commands → POST /devices/{uuid}/functions  (PATCH via Rails convention)
         → Headers: x-csrf-token
         → Body: _method=patch, authenticity_token, function[cmd_code]=XXXX,
                 function[cmd_value][]=VALUE (repeated for each value)
```

### Coordinator Merging

The coordinator (`coordinator.py`) merges data from both sources via `get_device_data(uuid)`:
1. Starts with the JSON discovery data as the base
2. Overlays the HTML-scraped `device` dict (takes precedence for overlapping keys)
3. Attaches `last_location` from HTML scraping

All entities read from this merged dict via `self._data` (device-level) and `self._location` (last_location sub-dict).

---

## 2. Multi-Model Support

**Critical:** Different watch models support different commands with different codes. The integration discovers capabilities dynamically at init — it does NOT hardcode per-model.

### Known Models

| Feature | Connect MOVE (model_id=27) | Connect UP (model_id=77) |
|---|---|---|
| GPS tracking cmd_code | `0078` | `0077` |
| GPS options | 10s / 5min / 10min | 5min / 10min / 1hr |
| Step counter cmd_code | `0079` | `0082` |
| Access lists (whitelist) | `0080`, `0081` | Not available |
| Change password | `0067` | Not available |
| Intercom (initiate call) | `0084` | Not available |
| SOS / Factory reset / Shutdown / Refresh / Alarm / Language / Find / Quiet times / Scene / Phonebook | All shared | All shared |

### How Discovery Works

1. **`coordinator.async_setup()`** calls `client.async_discover_capabilities(uuid)` for each device
2. This fetches `GET /devices/{uuid}/functions?list_only=true` and parses HTML for `<a href="...?function=XXXX">` links
3. For commands in `RADIO_COMMANDS` (GPS interval codes, profile mode), it also fetches the modal form to discover option values
4. Results are stored in `coordinator._capabilities[uuid]`
5. Entities check capabilities before creating themselves (e.g., step counter switch only created if 0079 or 0082 is discovered)

### Coordinator Capability API

```python
coordinator.get_capabilities(uuid)      # Full capabilities dict
coordinator.device_supports(uuid, "0084")  # Does device support intercom?
coordinator.device_find_code(uuid, ("0077", "0078"))  # Which GPS code?
coordinator.get_command_options(uuid, "0078")  # GPS interval options
```

---

## 3. Entity Reference

Each physical device (watch) creates the following HA entities. **Entities for model-specific commands are only created if the device supports them.**

### Device Tracker

| Entity ID pattern | `device_tracker.<name>` |
|---|---|
| **unique_id** | `{uuid}` |
| **Source** | Merged data |
| **Provides** | latitude, longitude, location_accuracy, battery_level, location_name (zone or address) |

**Extra state attributes:**
- `serial_number`, `uuid`, `status`, `phone_number`
- `location_type` (GPS/WIFI/LBS), `address`, `altitude`
- `signal_strength`, `satellite_count`
- `last_communication`, `last_location_update`
- `tariff_type`, `balance_eur` (from simcard data — the API field `balance_cents` is divided by 100 to get euros)
- `settings_synced` (boolean — whether settings have been read from the portal)
- `phonebook` (list of `{name, number}` dicts — present when synced)
- `whitelist` (list of phone number strings — present when synced)
- `alarms` (list of alarm strings — always present, `[]` when empty)
- `quiet_times` (list of `{start, end}` dicts — always present, `[]` when empty)

### Sensors (12 standard + 2 conditional)

#### Standard Sensors (always created, one per device)

| Key | Entity suffix | Source field | Unit | Notes |
|-----|--------------|-------------|------|-------|
| `battery` | `_battery` | `last_location.battery_percentage` | % | Standard battery device class |
| `sim_balance` | `_sim_balance` | `simcard.balance_cents` | EUR | **Value is cents, divided by 100** |
| `last_location_update` | `_last_location_update` | `last_location.last_location_update` | timestamp | ISO format |
| `last_communication` | `_last_communication` | `last_location.last_communication` | timestamp | ISO format |
| `signal_strength` | `_signal_strength` | `last_location.signal_strength` | % | |
| `satellite_count` | `_satellite_count` | `last_location.satellite_count` | count | 0 = no GPS fix |
| `speed` | `_speed` | `last_location.speed` | km/h | |
| `altitude` | `_altitude` | `last_location.altitude` | m | |
| `steps_today` | `_steps_today` | `last_location.step_count_day` | steps | Resets daily. Fallback: `meta_data.steps` |
| `accuracy` | `_accuracy` | `last_location.meta_data.accuracy_meters` | m | GPS accuracy radius |
| `heading` | `_heading` | `last_location.meta_data.course` | ° | Returns `unknown` when satellite_count is 0 or non-numeric |
| `status` | `_status` | `device.status` | enum | Device class ENUM with options: `gps`, `wifi`, `offline`. Value is lowercased from API. |

#### Conditional Sensors (only created if device supports the feature)

| Key | Entity suffix | Created if | Value | Attributes |
|-----|--------------|-----------|-------|------------|
| `phonebook` | `_phonebook` | Device supports CMD_PHONEBOOK (1315) | Contact count (integer) | `contacts`: list of `{name, number}` dicts |
| `whitelist` | `_whitelist` | Device supports CMD_WHITELIST_1 (0080) | Number count (integer) | `numbers`: list of phone number strings |

**Model differences for conditional sensors:**
- **Connect MOVE:** Both phonebook and whitelist sensors are created
- **Connect UP:** Only phonebook sensor is created (whitelist not supported)

### Binary Sensors

| Key | Entity suffix | Source field | Device class | Notes |
|-----|--------------|-------------|-------------|-------|
| `tumble` | `_fall_detected` | `last_location.meta_data.tumble` | safety | `"1"` = fall detected |

### Buttons

| Key | Entity suffix | Command code | Notes |
|-----|--------------|-------------|-------|
| `refresh_location` | `_refresh_location` | `0039` | Activates high-frequency GPS for ~2 min |
| `find_device` | `_find_device` | `1015` | Makes the watch ring |

### Switches (model-aware)

| Key | Entity suffix | Command code | Notes |
|-----|--------------|-------------|-------|
| `step_counter` | `_step_counter` | `0079` (MOVE) or `0082` (UP) | **Only created if device supports it.** `["1"]` to enable, no value to disable. Assumed state. Exposes `cmd_code` attribute. |

### Selects (model-aware, dynamically discovered)

| Key | Entity suffix | Command code | Notes |
|-----|--------------|-------------|-------|
| `gps_interval` | `_gps_tracking_interval` | `0078` (MOVE) or `0077` (UP) | **Only created if device supports it.** Options discovered dynamically. Exposes `cmd_code` attribute. |
| `profile_mode` | `_profile_mode` | `1116` | **Only created if device supports it.** Options discovered dynamically. |

---

## 4. Services Reference

All services accept targeting via `entity_id`, `device_id`, or `area_id`.

### Action Services

#### `one2track.send_message`
```yaml
service: one2track.send_message
target:
  device_id: <device_id>
data:
  message: "Time to come home!"
```

#### `one2track.force_update`
```yaml
service: one2track.force_update
target:
  device_id: <device_id>
```

#### `one2track.find_device`
```yaml
service: one2track.find_device
target:
  device_id: <device_id>
```

#### `one2track.intercom` (Connect MOVE only)
**Checks capability before executing.** Will error if device doesn't support it.
```yaml
service: one2track.intercom
target:
  device_id: <device_id>
data:
  phone_number: "0031612345678"
```

### Setting Services

#### `one2track.send_device_command`
Generic escape hatch — send any command code.
```yaml
service: one2track.send_device_command
target:
  device_id: <device_id>
data:
  cmd_code: "0039"
  cmd_values:
    - "value1"
```

#### `one2track.set_sos_number`
```yaml
data:
  phone_number: "0031612345678"
```

#### `one2track.set_alarms`
Format per alarm: `HH:MM-STATUS-MODE[-DDDDDDD]`. Send empty list to clear.
```yaml
data:
  alarms:
    - "07:00-1-2"
    - "08:30-1-3-1111100"
```

#### `one2track.set_phonebook`
```yaml
data:
  contacts:
    - name: "Papa"
      number: "0031612345678"
```

#### `one2track.add_phonebook_contact`
Syncs from portal before modifying. Replaces existing contact if name matches, otherwise appends.
```yaml
data:
  name: "Contact1"
  number: "0031612345678"
```

#### `one2track.remove_phonebook_contact`
Syncs from portal before modifying. Errors if name not found.
```yaml
data:
  name: "Contact1"
```

#### `one2track.set_whitelist` (Connect MOVE only)
**Checks capability before executing.** Maximum 10 numbers. Internally split across two command slots (0080 for 1-5, 0081 for 6-10).
```yaml
data:
  phone_numbers:
    - "0031612345678"
    - "0031687654321"
```

#### `one2track.add_whitelist_number` (Connect MOVE only)
**Checks capability before executing.** Syncs from portal before modifying. Errors if number already exists or list is full (max 10).
```yaml
data:
  phone_number: "0031612345678"
```

#### `one2track.remove_whitelist_number` (Connect MOVE only)
**Checks capability before executing.** Syncs from portal before modifying. Errors if number not found.
```yaml
data:
  phone_number: "0031612345678"
```

#### `one2track.set_quiet_times`
```yaml
data:
  windows:
    - start: "22:00"
      end: "07:00"
```

#### `one2track.set_language_timezone`
```yaml
data:
  language: "16"        # 1=English, 5=German, 16=Dutch
  utc_offset: "1.0"     # CET=1.0, CEST=2.0
```

#### `one2track.change_password` (Connect MOVE only)
**Checks capability before executing.**
```yaml
data:
  password: "123456"
```

#### `one2track.factory_reset`
**DANGEROUS.** Cannot be undone.

#### `one2track.remote_shutdown`
**DANGEROUS.** Cannot be turned back on via the app.

### Diagnostics Service

#### `one2track.get_raw_device_data`
Fetches live raw data from all sources and returns it as response data.

```yaml
service: one2track.get_raw_device_data
target:
  device_id: <device_id>
data: {}
```

**Response structure:**
```json
{
  "account_id": "12345",
  "json_api": { "device": { "uuid": "...", "device_model_id": 27, ... } },
  "html_scraped": {
    "device": { "...from var device JS var..." },
    "last_location": { "latitude": "52.xxx", "battery_percentage": 85, ... }
  },
  "capabilities": {
    "functions": { "0001": "SOS nummer", "0078": "GPS tracking", ... },
    "options": {}
  },
  "coordinator_data": { "...merged dict entities read from..." },
  "discovered_capabilities": {
    "functions": { "0001": "SOS nummer", "0078": "GPS tracking/powersave", ... },
    "options": {
      "0078": [
        {"value": "10", "label": "Every 10 seconds - High battery", "checked": false},
        {"value": "300", "label": "Every 5 minutes - Medium battery", "checked": true}
      ]
    }
  },
  "local_settings": {
    "phonebook": [{"name": "Contact1", "number": "0031612345678"}],
    "whitelist": ["0031612345678"],
    "alarms": ["07:00-1-2"],
    "quiet_times": [{"start": "22:00", "end": "07:00"}]
  }
}
```

**Notes:** If a data source fails, its key is replaced with an error key (e.g., `json_api_error` instead of `json_api`). The `local_settings` section shows the coordinator's current state for persistent settings.

---

## 5. Command Endpoint Details

All device commands use the Rails PATCH convention:
- **URL:** `POST https://www.one2trackgps.com/devices/{uuid}/functions`
- **Body:** `_method=patch`, `authenticity_token=<csrf>`, `function[cmd_code]=<CODE>`, `function[cmd_value][]=<VALUE>` (repeated for each value)
- **Headers:** `x-csrf-token: <csrf>`, `content-type: application/x-www-form-urlencoded; charset=UTF-8`

### Command Code Quick Reference

| cmd_code | Function | Models | cmd_value | Dangerous | Discover? |
|---|---|---|---|---|---|
| `0001` | SOS Number | All | Phone number | No | No |
| `0011` | Factory Reset | All | None | YES | No |
| `0039` | Refresh Location | All | None | No | No |
| `0048` | Remote Shutdown | All | None | YES | No |
| `0057` | Alarm List | All | `HH:MM-STATUS-MODE[-DDDDDDD]` | No | No |
| `0067` | Change Password | MOVE | 6-digit string | Yes | No |
| `0077` | GPS Interval | UP | seconds (radio) | No | YES |
| `0078` | GPS Interval | MOVE | seconds (radio) | No | YES |
| `0079` | Step Counter | MOVE | `1`=on / omit=off | No | No |
| `0080` | Access List 1 (1-5) | MOVE | 5x phone numbers | No | No |
| `0081` | Access List 2 (6-10) | MOVE | 5x phone numbers | No | No |
| `0082` | Step Counter | UP | `1`=on / omit=off | No | No |
| `0084` | Intercom | MOVE | Phone number | No | No |
| `0124` | Language & Timezone | All | Lang ID + UTC offset | No | No |
| `1015` | Find Device | All | None | No | No |
| `1107` | Quiet Times | All | `1,HHMM,HHMM,1[,1]` | No | No |
| `1116` | Scene Mode | All | `1`-`4` | No | Consider |
| `1315` | Phonebook | All | name+number pairs | No | No |

---

## 6. Known Limitations

1. **Step counter and select entities are assumed state.** No API to read the current setting back. State resets to default on HA restart.

2. **Capability discovery happens once at init.** If a watch is offline at HA startup, capabilities may not be discovered and model-specific entities won't be created until HA restarts.

3. **Status sensor is an ENUM with values `gps`, `wifi`, `offline`.** The raw API value is lowercased. May not update as frequently as HTML-scraped sensors.

4. **HTML scraping is fragile.** Parses `var device = {...}` and `var last_location = {...}` from inline JavaScript. Site changes could break silently.

5. **The `balance_cents` API field contains cents.** The value is divided by 100 to get euros. The attribute is named `balance_eur`.

6. **Heading reads `unknown` when satellite_count is 0.** Intentional — no GPS fix means no real heading data.

7. **Cookie name may vary.** The server may use `_iadmin` or `_session_id`. The client auto-detects which cookie name the server sends.

8. **Portal alarm form values may be malformed.** The One2Track portal sometimes returns JavaScript template fragments instead of rendered alarm values in form inputs. The integration validates synced alarm values (must match `HH:MM-...` format) and discards malformed ones, keeping local state.

9. **Portal phonebook writes may return HTTP 500 on success.** The integration handles this by updating local state optimistically. The next settings sync corrects any discrepancy.

10. **`alarms` and `quiet_times` device tracker attributes are always present.** They show `[]` when empty, allowing automations to distinguish "empty" from "not supported."

---

## 7. Test Procedures

### Basic Connectivity Test
1. Check the integration loaded: devices appear under Settings → Devices
2. Verify device tracker has latitude/longitude
3. Check `sensor.*_battery` has a percentage value
4. Check `sensor.*_status` shows one of: `gps`, `wifi`, `offline`

### Capability Discovery Test
1. Call `one2track.get_raw_device_data` with return_response
2. Check `discovered_capabilities.functions` — should list all commands the device supports
3. Check `discovered_capabilities.options` — GPS interval and profile mode should have option lists
4. Verify the GPS interval select and step counter switch exist (they're only created for supported devices)
5. Check the `cmd_code` attribute on select/switch entities — should match the discovered code for that model
6. Check `local_settings` — should show current phonebook, whitelist, alarms, and quiet_times state

### Multi-Model Entity Test

The integration creates different entities depending on device capabilities. Test that the correct entities exist for each model.

#### Expected entities per model

| Entity | Connect MOVE | Connect UP |
|--------|-------------|-----------|
| `device_tracker.<name>` | Yes | Yes |
| `sensor.<name>_battery` | Yes | Yes |
| `sensor.<name>_sim_balance` | Yes | Yes |
| `sensor.<name>_last_location_update` | Yes | Yes |
| `sensor.<name>_last_communication` | Yes | Yes |
| `sensor.<name>_signal_strength` | Yes | Yes |
| `sensor.<name>_satellite_count` | Yes | Yes |
| `sensor.<name>_speed` | Yes | Yes |
| `sensor.<name>_altitude` | Yes | Yes |
| `sensor.<name>_steps_today` | Yes | Yes |
| `sensor.<name>_accuracy` | Yes | Yes |
| `sensor.<name>_heading` | Yes | Yes |
| `sensor.<name>_status` | Yes | Yes |
| `sensor.<name>_phonebook` | Yes (if 1315 discovered) | Yes (if 1315 discovered) |
| `sensor.<name>_whitelist` | Yes (if 0080 discovered) | **No** (not supported) |
| `binary_sensor.<name>_fall_detected` | Yes | Yes |
| `button.<name>_refresh_location` | Yes | Yes |
| `button.<name>_find_device` | Yes | Yes |
| `switch.<name>_step_counter` | Yes (cmd_code 0079) | Yes (cmd_code 0082) |
| `select.<name>_gps_tracking_interval` | Yes (cmd_code 0078) | Yes (cmd_code 0077) |
| `select.<name>_profile_mode` | Yes (if 1116 discovered) | Yes (if 1116 discovered) |

#### Test steps
1. List all entities for each device under Settings → Devices
2. Verify Connect MOVE has whitelist sensor, Connect UP does not
3. Check `cmd_code` attribute on step counter switch: MOVE=`0079`, UP=`0082`
4. Check `cmd_code` attribute on GPS interval select: MOVE=`0078`, UP=`0077`
5. Verify GPS interval options differ: MOVE should offer 10s option, UP should not
6. Check phonebook sensor value = number of contacts, with `contacts` attribute showing the list

### Model-Specific Service Test

Services that require specific capabilities should error gracefully on unsupported devices.

| Service | Connect MOVE | Connect UP (expected error) |
|---------|-------------|---------------------------|
| `intercom` | Should work | `ServiceValidationError`: "does not support intercom — only available on Connect MOVE watches" |
| `set_whitelist` | Should work | `ServiceValidationError`: "does not support whitelist — only available on Connect MOVE watches" |
| `add_whitelist_number` | Should work | `ServiceValidationError`: "does not support whitelist" |
| `remove_whitelist_number` | Should work | `ServiceValidationError`: "does not support whitelist" |
| `change_password` | Should work | `ServiceValidationError`: "does not support password change — only available on Connect MOVE watches" |

**Test steps:**
1. Call `one2track.intercom` targeting a Connect UP device — verify the error message names the device and mentions Connect MOVE
2. Call `one2track.set_whitelist` targeting a Connect UP device — verify similar error
3. Call `one2track.change_password` targeting a Connect UP device — verify similar error
4. Repeat all three on a Connect MOVE device — verify they succeed (use safe test values)

### Settings Persistence Test
1. Set phonebook via `one2track.set_phonebook` with test contacts
2. Verify `sensor.*_phonebook` shows correct count and `contacts` attribute
3. Restart Home Assistant
4. Verify phonebook contacts survive the restart (loaded from persistent storage)
5. Repeat for alarms and quiet_times (check device tracker attributes)

### Service Targeting Test
Services must work with all three targeting methods:
```yaml
target:
  entity_id: device_tracker.my_watch
target:
  device_id: <ha_device_id>
target:
  area_id: <area_id>
```

### Data Accuracy Test
1. Call `one2track.get_raw_device_data` with return_response
2. Compare `json_api.device` fields with entity attributes
3. Compare `html_scraped.last_location` fields with sensor values
4. Check `coordinator_data` matches what entities display
5. Verify `balance_eur` attribute matches `sim_balance` sensor value
6. Compare `local_settings.phonebook` with `sensor.*_phonebook` `contacts` attribute

### Command Test (safe commands only)
- **find_device:** Watch should ring
- **force_update:** Should trigger GPS refresh, check if `last_location_update` advances
- **send_message:** Send test message, verify on watch screen

### Entity Registry Test
1. List all entities for each device
2. Every entity should have a state (not 404/unavailable unless watch is offline)
3. Model-specific entities should only exist for devices that support them
4. Conditional sensors (phonebook, whitelist) should only appear for devices with the corresponding capability
