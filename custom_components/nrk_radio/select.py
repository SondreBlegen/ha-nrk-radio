"""Which speaker NRK Radio plays on. Changing it mid-stream moves the stream."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import NrkConfigEntry
from .controller import RadioController
from .entity import NrkEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: NrkConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([SpeakerSelect(entry.runtime_data, entry.entry_id)])


class SpeakerSelect(NrkEntity, SelectEntity, RestoreEntity):
    _attr_translation_key = "speaker"

    def __init__(self, controller: RadioController, entry_id: str) -> None:
        super().__init__(controller, entry_id)
        self._attr_unique_id = f"{entry_id}_speaker"

    def _name(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        return (state and state.name) or entity_id

    @property
    def options(self) -> list[str]:
        return [self._name(e) for e in self.controller.speakers]

    @property
    def current_option(self) -> str | None:
        speaker = self.controller.speaker
        return self._name(speaker) if speaker else None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.attributes.get("entity_id") in self.controller.speakers:
            self.controller.speaker = last.attributes["entity_id"]
            self.controller.track_speaker()

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        # The entity id survives renames; restore uses it rather than the name.
        return {"entity_id": self.controller.speaker}

    async def async_select_option(self, option: str) -> None:
        for entity_id in self.controller.speakers:
            if self._name(entity_id) == option:
                await self.controller.async_set_speaker(entity_id)
                return
        raise HomeAssistantError(f"Unknown speaker '{option}'")
