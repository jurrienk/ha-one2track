"""Base entity for the One2Track integration."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import One2TrackCoordinator


class One2TrackEntity(CoordinatorEntity[One2TrackCoordinator]):
    """Base class for all One2Track entities.

    Provides shared device_info and data access for a specific watch UUID.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: One2TrackCoordinator, uuid: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._uuid = uuid

    @property
    def _data(self) -> dict[str, Any]:
        """Return merged device data for this watch."""
        return self.coordinator.get_device_data(self._uuid)

    @property
    def _location(self) -> dict[str, Any]:
        """Return last_location dict for this watch."""
        return self._data.get("last_location", {})

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info linking all entities to one HA device per watch."""
        data = self._data
        return DeviceInfo(
            identifiers={(DOMAIN, self._uuid)},
            serial_number=data.get("serial_number"),
            name=data.get("name", self._uuid),
        )
