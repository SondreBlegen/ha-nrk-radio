"""Base entity: one 'NRK Radio' device, state pushed from the controller."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .controller import RadioController


class NrkEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    # Entities whose state reflects playback re-render on every controller change.
    _follows_playback = True

    def __init__(self, controller: RadioController, entry_id: str) -> None:
        self.controller = controller
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="NRK Radio",
            manufacturer="NRK",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://radio.nrk.no",
        )

    async def async_added_to_hass(self) -> None:
        if self._follows_playback:
            self.async_on_remove(self.controller.add_listener(self.async_write_ha_state))
