"""Keep playing: when the queue runs out, carry on with the show's next episode."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import NrkConfigEntry
from .controller import RadioController
from .entity import NrkEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: NrkConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([KeepPlayingSwitch(entry.runtime_data, entry.entry_id)])


class KeepPlayingSwitch(NrkEntity, SwitchEntity, RestoreEntity):
    _attr_translation_key = "keep_playing"
    _attr_icon = "mdi:playlist-play"

    def __init__(self, controller: RadioController, entry_id: str) -> None:
        super().__init__(controller, entry_id)
        self._attr_unique_id = f"{entry_id}_keep_playing"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self.controller.set_keep_playing(last.state == STATE_ON)

    @property
    def is_on(self) -> bool:
        return self.controller.keep_playing

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.controller.set_keep_playing(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.controller.set_keep_playing(False)
