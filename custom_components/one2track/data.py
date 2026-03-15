"""Custom types for the One2Track integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .api import One2TrackApiClient
    from .coordinator import One2TrackCoordinator


type One2TrackConfigEntry = ConfigEntry[One2TrackData]


@dataclass
class One2TrackData:
    """Runtime data for a One2Track config entry."""

    client: One2TrackApiClient
    coordinator: One2TrackCoordinator
