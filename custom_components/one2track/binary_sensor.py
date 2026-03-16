"""Binary sensor platform for One2Track."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .entity import One2TrackEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .data import One2TrackConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: One2TrackConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up One2Track binary sensor entities."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        One2TrackTumbleSensor(coordinator, device["uuid"])
        for device in coordinator.device_list
    )


class One2TrackTumbleSensor(One2TrackEntity, BinarySensorEntity):
    """Binary sensor for fall detection."""

    _attr_translation_key = "tumble"
    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(self, coordinator, uuid: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, uuid)
        self._attr_unique_id = f"{uuid}_tumble"

    @property
    def is_on(self) -> bool | None:
        """Return True if a fall was detected."""
        meta = self._location.get("meta_data")
        if isinstance(meta, dict):
            return meta.get("tumble") == "1"
        return None
