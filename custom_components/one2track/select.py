"""Select platform for One2Track — setting selectors.

GPS interval and profile mode selects are created dynamically based on
each device's discovered capabilities (command codes and option values
differ per watch model).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import EntityCategory

from .const import (
    CMD_PROFILE_MODE,
    GPS_INTERVAL_CODES,
    GPS_INTERVAL_OPTIONS_FALLBACK,
    PROFILE_MODE_OPTIONS_FALLBACK,
)
from .entity import One2TrackEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import One2TrackCoordinator
    from .data import One2TrackConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: One2TrackConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up One2Track setting selects based on discovered capabilities."""
    coordinator = entry.runtime_data.coordinator
    entities: list[SelectEntity] = []

    for device in coordinator.device_list:
        uuid = device["uuid"]

        # GPS interval — discover which code this device uses (0077 or 0078)
        gps_code = coordinator.device_find_code(uuid, GPS_INTERVAL_CODES)
        if gps_code:
            discovered_opts = coordinator.get_command_options(uuid, gps_code)
            if discovered_opts:
                value_map = {
                    o["value"]: o["label"] for o in discovered_opts
                }
                current = next(
                    (o["label"] for o in discovered_opts if o.get("checked")),
                    None,
                )
            else:
                value_map = GPS_INTERVAL_OPTIONS_FALLBACK
                current = None
            entities.append(
                One2TrackDynamicSelect(
                    coordinator, uuid,
                    key="gps_interval",
                    translation_key="gps_interval",
                    icon="mdi:map-marker-distance",
                    cmd_code=gps_code,
                    value_map=value_map,
                    current_option=current,
                )
            )

        # Profile / scene mode
        if coordinator.device_supports(uuid, CMD_PROFILE_MODE):
            discovered_opts = coordinator.get_command_options(uuid, CMD_PROFILE_MODE)
            if discovered_opts:
                value_map = {
                    o["value"]: o["label"] for o in discovered_opts
                }
                current = next(
                    (o["label"] for o in discovered_opts if o.get("checked")),
                    None,
                )
            else:
                value_map = PROFILE_MODE_OPTIONS_FALLBACK
                current = None
            entities.append(
                One2TrackDynamicSelect(
                    coordinator, uuid,
                    key="profile_mode",
                    translation_key="profile_mode",
                    icon="mdi:bell-cog",
                    cmd_code=CMD_PROFILE_MODE,
                    value_map=value_map,
                    current_option=current,
                )
            )

    async_add_entities(entities)


class One2TrackDynamicSelect(One2TrackEntity, SelectEntity):
    """A select entity for a One2Track device setting.

    Created dynamically based on discovered capabilities — the command code
    and option values are determined at runtime, not hardcoded.
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: One2TrackCoordinator,
        uuid: str,
        *,
        key: str,
        translation_key: str,
        icon: str,
        cmd_code: str,
        value_map: dict[str, str],
        current_option: str | None = None,
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator, uuid)
        self._attr_unique_id = f"{uuid}_{key}"
        self._attr_translation_key = translation_key
        self._attr_icon = icon
        self._cmd_code = cmd_code
        self._value_map = value_map
        self._label_to_value = {v: k for k, v in value_map.items()}
        self._attr_options = list(value_map.values())
        self._attr_current_option = current_option or (
            self._attr_options[0] if self._attr_options else None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the resolved command code for debugging."""
        return {"cmd_code": self._cmd_code}

    async def async_select_option(self, option: str) -> None:
        """Send the selected setting to the watch."""
        api_value = self._label_to_value.get(option)
        if api_value is None:
            return
        success = await self.coordinator.client.async_send_command(
            self._uuid, self._cmd_code, [api_value]
        )
        if success:
            self._attr_current_option = option
            self.async_write_ha_state()
