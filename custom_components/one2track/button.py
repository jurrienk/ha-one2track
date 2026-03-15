"""Button platform for One2Track — action buttons."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription

from .const import CMD_FIND_DEVICE, CMD_REFRESH_LOCATION
from .entity import One2TrackEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import One2TrackCoordinator
    from .data import One2TrackConfigEntry


@dataclass(frozen=True, kw_only=True)
class One2TrackButtonDescription(ButtonEntityDescription):
    """Describes a One2Track action button."""

    cmd_code: str
    cmd_values: list[str] | None = None


BUTTON_DESCRIPTIONS: tuple[One2TrackButtonDescription, ...] = (
    One2TrackButtonDescription(
        key="refresh_location",
        translation_key="refresh_location",
        icon="mdi:crosshairs-gps",
        cmd_code=CMD_REFRESH_LOCATION,
    ),
    One2TrackButtonDescription(
        key="find_device",
        translation_key="find_device",
        icon="mdi:bell-ring",
        cmd_code=CMD_FIND_DEVICE,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: One2TrackConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up One2Track action buttons."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        One2TrackButton(coordinator, device["uuid"], desc)
        for device in coordinator.device_list
        for desc in BUTTON_DESCRIPTIONS
    )


class One2TrackButton(One2TrackEntity, ButtonEntity):
    """An action button for a One2Track device."""

    entity_description: One2TrackButtonDescription

    def __init__(
        self,
        coordinator: One2TrackCoordinator,
        uuid: str,
        description: One2TrackButtonDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, uuid)
        self.entity_description = description
        self._attr_unique_id = f"{uuid}_{description.key}"

    async def async_press(self) -> None:
        """Handle button press — send the command."""
        desc = self.entity_description
        await self.coordinator.client.async_send_command(
            self._uuid, desc.cmd_code, desc.cmd_values
        )
        await self.coordinator.async_request_refresh()
