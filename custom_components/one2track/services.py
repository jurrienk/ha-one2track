"""Service handlers for the One2Track integration."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .api import One2TrackApiClient
from .const import (
    CMD_ALARMS,
    CMD_CHANGE_PASSWORD,
    CMD_FACTORY_RESET,
    CMD_FIND_DEVICE,
    CMD_INTERCOM,
    CMD_LANGUAGE_TIMEZONE,
    CMD_PHONEBOOK,
    CMD_QUIET_TIMES,
    CMD_REFRESH_LOCATION,
    CMD_REMOTE_SHUTDOWN,
    CMD_SOS_NUMBER,
    CMD_WHITELIST_1,
    CMD_WHITELIST_2,
    DOMAIN,
    LOGGER,
)
from .coordinator import One2TrackCoordinator

# ── Action services (perform an action on the watch) ──────────────
SERVICE_SEND_MESSAGE = "send_message"
SERVICE_FORCE_UPDATE = "force_update"
SERVICE_FIND_DEVICE = "find_device"
SERVICE_INTERCOM = "intercom"

# ── Setting services (change a watch setting) ─────────────────────
SERVICE_SEND_DEVICE_COMMAND = "send_device_command"
SERVICE_SET_SOS_NUMBER = "set_sos_number"
SERVICE_SET_ALARMS = "set_alarms"
SERVICE_SET_PHONEBOOK = "set_phonebook"
SERVICE_SET_WHITELIST = "set_whitelist"
SERVICE_ADD_PHONEBOOK_CONTACT = "add_phonebook_contact"
SERVICE_REMOVE_PHONEBOOK_CONTACT = "remove_phonebook_contact"
SERVICE_ADD_WHITELIST_NUMBER = "add_whitelist_number"
SERVICE_REMOVE_WHITELIST_NUMBER = "remove_whitelist_number"
SERVICE_SET_QUIET_TIMES = "set_quiet_times"
SERVICE_SET_LANGUAGE_TIMEZONE = "set_language_timezone"
SERVICE_CHANGE_PASSWORD = "change_password"
SERVICE_FACTORY_RESET = "factory_reset"
SERVICE_REMOTE_SHUTDOWN = "remote_shutdown"
SERVICE_GET_RAW_DATA = "get_raw_device_data"

ALL_SERVICES = (
    SERVICE_SEND_MESSAGE,
    SERVICE_FORCE_UPDATE,
    SERVICE_FIND_DEVICE,
    SERVICE_INTERCOM,
    SERVICE_SEND_DEVICE_COMMAND,
    SERVICE_SET_SOS_NUMBER,
    SERVICE_SET_ALARMS,
    SERVICE_SET_PHONEBOOK,
    SERVICE_SET_WHITELIST,
    SERVICE_ADD_PHONEBOOK_CONTACT,
    SERVICE_REMOVE_PHONEBOOK_CONTACT,
    SERVICE_ADD_WHITELIST_NUMBER,
    SERVICE_REMOVE_WHITELIST_NUMBER,
    SERVICE_SET_QUIET_TIMES,
    SERVICE_SET_LANGUAGE_TIMEZONE,
    SERVICE_CHANGE_PASSWORD,
    SERVICE_FACTORY_RESET,
    SERVICE_REMOTE_SHUTDOWN,
    SERVICE_GET_RAW_DATA,
)


def _resolve_device(
    hass: HomeAssistant, call: ServiceCall
) -> tuple[str, One2TrackApiClient, One2TrackCoordinator]:
    """Resolve service call targets to (uuid, client, coordinator).

    Supports entity_id, device_id, and area_id targeting (standard HA).
    """
    entity_ids: set[str] = set()

    # Collect entity_ids from call.data (legacy) and from target selector
    for source in (call.data, call.target if hasattr(call, "target") and call.target else {}):
        raw = source.get("entity_id", [])
        if isinstance(raw, str):
            entity_ids.add(raw)
        elif isinstance(raw, list):
            entity_ids.update(raw)

    # Resolve device_id targets → entity_ids
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    for source in (call.data, call.target if hasattr(call, "target") and call.target else {}):
        raw_devs = source.get("device_id", [])
        if isinstance(raw_devs, str):
            raw_devs = [raw_devs]
        for dev_id in raw_devs:
            for ent_entry in er.async_entries_for_device(ent_reg, dev_id):
                if ent_entry.platform == DOMAIN:
                    entity_ids.add(ent_entry.entity_id)

        raw_areas = source.get("area_id", [])
        if isinstance(raw_areas, str):
            raw_areas = [raw_areas]
        for area_id in raw_areas:
            for dev_entry in dr.async_entries_for_area(dev_reg, area_id):
                for ent_entry in er.async_entries_for_device(ent_reg, dev_entry.id):
                    if ent_entry.platform == DOMAIN:
                        entity_ids.add(ent_entry.entity_id)

    if not entity_ids:
        raise HomeAssistantError("No target entity or device specified")

    for entity_id in entity_ids:
        entry = ent_reg.async_get(entity_id)
        if not entry or entry.platform != DOMAIN:
            continue

        unique_id = entry.unique_id
        for config_entry in hass.config_entries.async_entries(DOMAIN):
            if not hasattr(config_entry, "runtime_data") or not config_entry.runtime_data:
                continue
            coordinator = config_entry.runtime_data.coordinator
            client = config_entry.runtime_data.client
            for device in coordinator.device_list:
                dev_uuid = device.get("uuid", "")
                if unique_id == dev_uuid or unique_id.startswith(dev_uuid + "_"):
                    return dev_uuid, client, coordinator

    raise HomeAssistantError(f"Could not resolve One2Track device from targets")


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register One2Track services."""
    if hass.services.has_service(DOMAIN, SERVICE_SEND_MESSAGE):
        return

    # ── Action: Send message ──────────────────────────────────────

    async def handle_send_message(call: ServiceCall) -> None:
        uuid, client, _ = _resolve_device(hass, call)
        message = call.data["message"]
        LOGGER.info("Sending message to %s: %s", uuid, message)
        if not await client.async_send_message(uuid, message):
            raise HomeAssistantError("Failed to send message")

    # ── Action: Force update (refresh location) ───────────────────

    async def handle_force_update(call: ServiceCall) -> None:
        uuid, client, coordinator = _resolve_device(hass, call)
        LOGGER.info("Requesting location refresh for %s", uuid)
        if not await client.async_send_command(uuid, CMD_REFRESH_LOCATION):
            raise HomeAssistantError("Failed to activate positioning mode")
        await coordinator.async_request_refresh()

    # ── Action: Find device (ring the watch) ──────────────────────

    async def handle_find_device(call: ServiceCall) -> None:
        uuid, client, _ = _resolve_device(hass, call)
        LOGGER.info("Ringing device %s", uuid)
        if not await client.async_send_command(uuid, CMD_FIND_DEVICE):
            raise HomeAssistantError("Failed to ring device")

    # ── Action: Intercom (make watch call a number) ───────────────

    async def handle_intercom(call: ServiceCall) -> None:
        uuid, client, coordinator = _resolve_device(hass, call)
        if not coordinator.device_supports(uuid, CMD_INTERCOM):
            dev_name = coordinator.get_device_data(uuid).get("name", uuid)
            raise ServiceValidationError(
                f"'{dev_name}' does not support intercom — this feature is "
                f"only available on Connect MOVE watches"
            )
        phone = call.data["phone_number"]
        LOGGER.info("Initiating intercom call from %s to %s", uuid, phone)
        if not await client.async_send_command(uuid, CMD_INTERCOM, [phone]):
            raise HomeAssistantError("Failed to initiate intercom call")

    # ── Setting: Send device command (generic) ────────────────────

    async def handle_send_device_command(call: ServiceCall) -> None:
        uuid, client, _ = _resolve_device(hass, call)
        cmd_code = call.data["cmd_code"]
        cmd_values = call.data.get("cmd_values", [])
        LOGGER.info("Sending command %s to %s", cmd_code, uuid)
        if not await client.async_send_command(uuid, cmd_code, cmd_values or None):
            raise HomeAssistantError(f"Failed to send command {cmd_code}")

    # ── Setting: SOS number ───────────────────────────────────────

    async def handle_set_sos_number(call: ServiceCall) -> None:
        uuid, client, _ = _resolve_device(hass, call)
        phone = call.data["phone_number"]
        if not await client.async_send_command(uuid, CMD_SOS_NUMBER, [phone]):
            raise HomeAssistantError("Failed to set SOS number")

    # ── Setting: Alarms ───────────────────────────────────────────

    async def handle_set_alarms(call: ServiceCall) -> None:
        uuid, client, coordinator = _resolve_device(hass, call)
        alarms = call.data.get("alarms", [])
        if not await client.async_send_command(uuid, CMD_ALARMS, alarms or None):
            raise HomeAssistantError("Failed to set alarms")
        coordinator.set_alarms(uuid, alarms)

    # ── Setting: Phonebook ────────────────────────────────────────

    async def _send_phonebook(uuid: str, client: One2TrackApiClient, contacts: list[dict]) -> None:
        """Send full phonebook to device.

        The One2Track portal sometimes returns HTTP 500 even when the write
        succeeds (BUG-3). We log a warning but do not raise, so the caller
        can always update local state optimistically. The next settings sync
        will correct any discrepancy.
        """
        values = []
        for contact in contacts:
            values.append(contact["name"])
            values.append(contact["number"])
        if not await client.async_send_command(uuid, CMD_PHONEBOOK, values or None):
            LOGGER.warning(
                "Phonebook command for %s returned a non-200 response. "
                "The write may still have succeeded (known portal quirk). "
                "Local state will be updated optimistically.",
                uuid,
            )

    async def handle_set_phonebook(call: ServiceCall) -> None:
        uuid, client, coordinator = _resolve_device(hass, call)
        contacts = call.data.get("contacts", [])
        await _send_phonebook(uuid, client, contacts)
        coordinator.set_phonebook(uuid, contacts)

    # ── Setting: Whitelist ────────────────────────────────────────

    async def _send_whitelist(uuid: str, client: One2TrackApiClient, coordinator: One2TrackCoordinator, numbers: list[str]) -> None:
        """Send full whitelist to device."""
        if not coordinator.device_supports(uuid, CMD_WHITELIST_1):
            dev_name = coordinator.get_device_data(uuid).get("name", uuid)
            raise ServiceValidationError(
                f"'{dev_name}' does not support whitelist — this feature is "
                f"only available on Connect MOVE watches"
            )
        padded = (numbers + [""] * 10)[:10]
        if not await client.async_send_command(uuid, CMD_WHITELIST_1, padded[:5]):
            raise HomeAssistantError("Failed to set whitelist (slots 1-5)")
        if not await client.async_send_command(uuid, CMD_WHITELIST_2, padded[5:]):
            raise HomeAssistantError("Failed to set whitelist (slots 6-10)")

    async def handle_set_whitelist(call: ServiceCall) -> None:
        uuid, client, coordinator = _resolve_device(hass, call)
        numbers = call.data.get("phone_numbers", [])
        await _send_whitelist(uuid, client, coordinator, numbers)
        coordinator.set_whitelist(uuid, numbers)

    # ── Setting: Quiet times ──────────────────────────────────────

    # ── Add/remove phonebook contacts ───────────────────────────────

    async def handle_add_phonebook_contact(call: ServiceCall) -> None:
        uuid, client, coordinator = _resolve_device(hass, call)
        await coordinator.async_refresh_settings(uuid)
        if not coordinator.is_settings_synced(uuid):
            raise ServiceValidationError(
                "Phonebook state is unknown — settings could not be read from the "
                "watch. Use one2track.set_phonebook first to set the full contact "
                "list, then use add/remove for individual changes."
            )
        name = call.data["name"]
        number = call.data["number"]
        contacts = coordinator.get_phonebook(uuid)
        # Replace if name already exists, otherwise append
        contacts = [c for c in contacts if c["name"] != name]
        contacts.append({"name": name, "number": number})
        await _send_phonebook(uuid, client, contacts)
        coordinator.set_phonebook(uuid, contacts)

    async def handle_remove_phonebook_contact(call: ServiceCall) -> None:
        uuid, client, coordinator = _resolve_device(hass, call)
        await coordinator.async_refresh_settings(uuid)
        if not coordinator.is_settings_synced(uuid):
            raise ServiceValidationError(
                "Phonebook state is unknown — settings could not be read from the "
                "watch. Use one2track.set_phonebook first to set the full contact "
                "list, then use add/remove for individual changes."
            )
        name = call.data["name"]
        contacts = coordinator.get_phonebook(uuid)
        new_contacts = [c for c in contacts if c["name"] != name]
        if len(new_contacts) == len(contacts):
            raise ServiceValidationError(
                f"Contact '{name}' not found in phonebook"
            )
        await _send_phonebook(uuid, client, new_contacts)
        coordinator.set_phonebook(uuid, new_contacts)

    # ── Add/remove whitelist numbers ─────────────────────────────────

    async def handle_add_whitelist_number(call: ServiceCall) -> None:
        uuid, client, coordinator = _resolve_device(hass, call)
        await coordinator.async_refresh_settings(uuid)
        if not coordinator.is_settings_synced(uuid):
            raise ServiceValidationError(
                "Whitelist state is unknown — settings could not be read from the "
                "watch. Use one2track.set_whitelist first to set the full number "
                "list, then use add/remove for individual changes."
            )
        number = call.data["phone_number"]
        numbers = coordinator.get_whitelist(uuid)
        if number in numbers:
            raise ServiceValidationError(
                f"Number '{number}' is already in the whitelist"
            )
        if len(numbers) >= 10:
            raise ServiceValidationError(
                "Whitelist is full (maximum 10 numbers). Remove a number first, "
                "or use one2track.set_whitelist to replace the entire list."
            )
        numbers.append(number)
        await _send_whitelist(uuid, client, coordinator, numbers)
        coordinator.set_whitelist(uuid, numbers)

    async def handle_remove_whitelist_number(call: ServiceCall) -> None:
        uuid, client, coordinator = _resolve_device(hass, call)
        await coordinator.async_refresh_settings(uuid)
        if not coordinator.is_settings_synced(uuid):
            raise ServiceValidationError(
                "Whitelist state is unknown — settings could not be read from the "
                "watch. Use one2track.set_whitelist first to set the full number "
                "list, then use add/remove for individual changes."
            )
        number = call.data["phone_number"]
        numbers = coordinator.get_whitelist(uuid)
        if number not in numbers:
            raise ServiceValidationError(
                f"Number '{number}' not found in whitelist"
            )
        numbers.remove(number)
        await _send_whitelist(uuid, client, coordinator, numbers)
        coordinator.set_whitelist(uuid, numbers)

    # ── Setting: Quiet times ──────────────────────────────────────

    async def handle_set_quiet_times(call: ServiceCall) -> None:
        uuid, client, coordinator = _resolve_device(hass, call)
        windows = call.data.get("windows", [])
        values = []
        for i, window in enumerate(windows):
            start = window["start"].replace(":", "")
            end = window["end"].replace(":", "")
            entry = f"1,{start},{end},1"
            if i == len(windows) - 1:
                entry += ",1"
            values.append(entry)
        if not await client.async_send_command(uuid, CMD_QUIET_TIMES, values or None):
            raise HomeAssistantError("Failed to set quiet times")
        coordinator.set_quiet_times(uuid, windows)

    # ── Setting: Language & timezone ──────────────────────────────

    async def handle_set_language_timezone(call: ServiceCall) -> None:
        uuid, client, _ = _resolve_device(hass, call)
        language = str(call.data["language"])
        utc_offset = str(call.data["utc_offset"])
        if not await client.async_send_command(uuid, CMD_LANGUAGE_TIMEZONE, [language, utc_offset]):
            raise HomeAssistantError("Failed to set language/timezone")

    # ── Setting: Change password ──────────────────────────────────

    async def handle_change_password(call: ServiceCall) -> None:
        uuid, client, coordinator = _resolve_device(hass, call)
        if not coordinator.device_supports(uuid, CMD_CHANGE_PASSWORD):
            dev_name = coordinator.get_device_data(uuid).get("name", uuid)
            raise ServiceValidationError(
                f"'{dev_name}' does not support password change — this feature "
                f"is only available on Connect MOVE watches"
            )
        password = call.data["password"]
        LOGGER.warning("Changing password for device %s", uuid)
        if not await client.async_send_command(uuid, CMD_CHANGE_PASSWORD, [password]):
            raise HomeAssistantError("Failed to change password")

    # ── Dangerous: Factory reset ──────────────────────────────────

    async def handle_factory_reset(call: ServiceCall) -> None:
        uuid, client, _ = _resolve_device(hass, call)
        LOGGER.warning("Factory resetting device %s — this cannot be undone!", uuid)
        if not await client.async_send_command(uuid, CMD_FACTORY_RESET):
            raise HomeAssistantError("Failed to send factory reset")

    # ── Dangerous: Remote shutdown ────────────────────────────────

    async def handle_remote_shutdown(call: ServiceCall) -> None:
        uuid, client, _ = _resolve_device(hass, call)
        LOGGER.warning("Remotely shutting down device %s — cannot be re-enabled remotely!", uuid)
        if not await client.async_send_command(uuid, CMD_REMOTE_SHUTDOWN):
            raise HomeAssistantError("Failed to send remote shutdown")

    # ── Diagnostics: Get raw live data ─────────────────────────────

    async def handle_get_raw_data(call: ServiceCall) -> dict:
        uuid, client, coordinator = _resolve_device(hass, call)
        LOGGER.info("Fetching raw live data for %s", uuid)
        raw = await client.async_get_raw_device_data(uuid)
        raw["coordinator_data"] = coordinator.get_device_data(uuid)
        raw["discovered_capabilities"] = coordinator.get_capabilities(uuid)
        raw["local_settings"] = {
            "phonebook": coordinator.get_phonebook(uuid),
            "whitelist": coordinator.get_whitelist(uuid),
            "alarms": coordinator.get_alarms(uuid),
            "quiet_times": coordinator.get_quiet_times(uuid),
        }
        return raw

    # ── Shared target keys (allow entity_id / device_id / area_id) ──
    TARGET_KEYS = {
        vol.Optional("entity_id"): vol.Any(str, [str]),
        vol.Optional("device_id"): vol.Any(str, [str]),
        vol.Optional("area_id"): vol.Any(str, [str]),
    }

    # ── Register all services ─────────────────────────────────────

    # Actions
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_MESSAGE, handle_send_message,
        schema=vol.Schema({
            **TARGET_KEYS,
            vol.Required("message"): str,
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_FORCE_UPDATE, handle_force_update,
        schema=vol.Schema({**TARGET_KEYS}),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_FIND_DEVICE, handle_find_device,
        schema=vol.Schema({**TARGET_KEYS}),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_INTERCOM, handle_intercom,
        schema=vol.Schema({
            **TARGET_KEYS,
            vol.Required("phone_number"): str,
        }),
    )

    # Settings
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_DEVICE_COMMAND, handle_send_device_command,
        schema=vol.Schema({
            **TARGET_KEYS,
            vol.Required("cmd_code"): str,
            vol.Optional("cmd_values", default=[]): vol.All(
                vol.Any(str, [str]),
                lambda v: [v] if isinstance(v, str) else v,
            ),
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_SOS_NUMBER, handle_set_sos_number,
        schema=vol.Schema({
            **TARGET_KEYS,
            vol.Required("phone_number"): str,
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_ALARMS, handle_set_alarms,
        schema=vol.Schema({
            **TARGET_KEYS,
            vol.Optional("alarms", default=[]): [str],
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_PHONEBOOK, handle_set_phonebook,
        schema=vol.Schema({
            **TARGET_KEYS,
            vol.Optional("contacts", default=[]): [
                vol.Schema({
                    vol.Required("name"): str,
                    vol.Required("number"): str,
                })
            ],
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_WHITELIST, handle_set_whitelist,
        schema=vol.Schema({
            **TARGET_KEYS,
            vol.Required("phone_numbers"): [str],
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_PHONEBOOK_CONTACT, handle_add_phonebook_contact,
        schema=vol.Schema({
            **TARGET_KEYS,
            vol.Required("name"): str,
            vol.Required("number"): str,
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_PHONEBOOK_CONTACT, handle_remove_phonebook_contact,
        schema=vol.Schema({
            **TARGET_KEYS,
            vol.Required("name"): str,
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_WHITELIST_NUMBER, handle_add_whitelist_number,
        schema=vol.Schema({
            **TARGET_KEYS,
            vol.Required("phone_number"): str,
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_WHITELIST_NUMBER, handle_remove_whitelist_number,
        schema=vol.Schema({
            **TARGET_KEYS,
            vol.Required("phone_number"): str,
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_QUIET_TIMES, handle_set_quiet_times,
        schema=vol.Schema({
            **TARGET_KEYS,
            vol.Optional("windows", default=[]): [
                vol.Schema({
                    vol.Required("start"): str,
                    vol.Required("end"): str,
                })
            ],
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_LANGUAGE_TIMEZONE, handle_set_language_timezone,
        schema=vol.Schema({
            **TARGET_KEYS,
            vol.Required("language"): vol.In(["1", "5", "16"]),
            vol.Required("utc_offset"): str,
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CHANGE_PASSWORD, handle_change_password,
        schema=vol.Schema({
            **TARGET_KEYS,
            vol.Required("password"): vol.All(str, vol.Length(min=6, max=6)),
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_FACTORY_RESET, handle_factory_reset,
        schema=vol.Schema({**TARGET_KEYS}),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REMOTE_SHUTDOWN, handle_remote_shutdown,
        schema=vol.Schema({**TARGET_KEYS}),
    )

    # Diagnostics
    hass.services.async_register(
        DOMAIN, SERVICE_GET_RAW_DATA, handle_get_raw_data,
        schema=vol.Schema({**TARGET_KEYS}),
        supports_response=SupportsResponse.ONLY,
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload One2Track services."""
    for service in ALL_SERVICES:
        hass.services.async_remove(DOMAIN, service)
