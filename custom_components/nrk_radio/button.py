"""One-tap buttons: a favourite channel, or the first episode of a favourite show."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NrkConfigEntry
from .api import NrkError
from .const import KIND_CHANNEL
from .controller import RadioController
from .entity import NrkEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: NrkConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    controller = entry.runtime_data
    entities: list[PlayButton] = []
    try:
        channels = {c.id: c for c in await controller.api.channels()}
    except NrkError:
        channels = {}  # fall back to ids as names; the buttons still work
    for channel_id in controller.favourite_channels:
        channel = channels.get(channel_id)
        entities.append(
            PlayButton(
                controller,
                entry.entry_id,
                f"{KIND_CHANNEL}/{channel_id}",
                channel.title if channel else channel_id,
                channel.image if channel else None,
                "mdi:radio",
            )
        )
    for ref in controller.favourite_shows:
        try:
            show = await controller.api.show(*ref.split("/", 1))
            name, image = show.title, show.image
        except NrkError:
            name, image = ref.split("/", 1)[1], None
        entities.append(PlayButton(controller, entry.entry_id, ref, name, image, "mdi:podcast"))
    async_add_entities(entities)


class PlayButton(NrkEntity, ButtonEntity):
    _follows_playback = False

    def __init__(
        self,
        controller: RadioController,
        entry_id: str,
        ref: str,
        name: str,
        image: str | None,
        icon: str,
    ) -> None:
        super().__init__(controller, entry_id)
        self._ref = ref
        self._attr_unique_id = f"{entry_id}_{ref.replace('/', '_')}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_entity_picture = image

    async def async_press(self) -> None:
        await self.controller.async_play(self._ref)
