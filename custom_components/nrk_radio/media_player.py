"""The NRK Radio player: a remote for whichever speaker is selected."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    ATTR_MEDIA_DURATION,
    ATTR_MEDIA_EXTRA,
    ATTR_MEDIA_POSITION,
    ATTR_MEDIA_POSITION_UPDATED_AT,
    ATTR_MEDIA_VOLUME_LEVEL,
    ATTR_MEDIA_VOLUME_MUTED,
    BrowseMedia,
    MediaPlayerEnqueue,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    SearchMedia,
    SearchMediaQuery,
)
from homeassistant.const import STATE_OFF, STATE_PAUSED, STATE_PLAYING
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later

from . import NrkConfigEntry
from .api import NrkError
from .const import DOMAIN, KIND_CHANNEL
from .controller import RadioController
from .entity import NrkEntity

_LOGGER = logging.getLogger(__name__)

_SPEAKER_STATES = {
    STATE_PLAYING: MediaPlayerState.PLAYING,
    STATE_PAUSED: MediaPlayerState.PAUSED,
    "buffering": MediaPlayerState.BUFFERING,
}

SERVICE_REMOVE_FROM_QUEUE = "remove_from_queue"


async def async_setup_entry(
    hass: HomeAssistant, entry: NrkConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([NrkRadioPlayer(entry.runtime_data, entry.entry_id)])
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_REMOVE_FROM_QUEUE,
        {vol.Required("position"): cv.positive_int},
        "async_remove_from_queue",
    )


def _strip_media_source(media_id: str) -> str:
    """'media-source://nrk_radio/series/x' -> 'series/x'; short forms pass through."""
    prefix = f"{media_source.URI_SCHEME}{DOMAIN}"
    if media_id.startswith(prefix):
        return media_id.removeprefix(prefix).lstrip("/")
    if media_source.is_media_source_id(media_id):
        raise HomeAssistantError("NRK Radio can only play NRK media")
    return media_id


class NrkRadioPlayer(NrkEntity, MediaPlayerEntity):
    _attr_name = None
    _attr_media_image_remotely_accessible = True
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.SEEK
        | MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.MEDIA_ENQUEUE
        | MediaPlayerEntityFeature.CLEAR_PLAYLIST
        | MediaPlayerEntityFeature.BROWSE_MEDIA
        | MediaPlayerEntityFeature.SEARCH_MEDIA
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.VOLUME_STEP
    )

    def __init__(self, controller: RadioController, entry_id: str) -> None:
        super().__init__(controller, entry_id)
        self._attr_unique_id = f"{entry_id}_player"
        self._sources: dict[str, str] = {}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._async_load_sources()

    async def _async_load_sources(self) -> None:
        """Source list: favourite channels, then favourite shows."""
        c = self.controller
        sources: dict[str, str] = {}
        try:
            channels = {ch.id: ch for ch in await c.api.channels()}
            for channel_id in c.favourite_channels:
                if channel_id in channels:
                    sources[channels[channel_id].title] = f"{KIND_CHANNEL}/{channel_id}"
            for ref in c.favourite_shows:
                show = await c.api.show(*ref.split("/", 1))
                sources[show.title] = ref
        except NrkError as err:
            # NRK being down mustn't break the player; try again later.
            _LOGGER.warning("Could not load NRK sources, retrying in 5 min: %s", err)
            self.async_on_remove(async_call_later(self.hass, 300, self._async_retry_sources))
        self._sources = sources
        self.async_write_ha_state()

    async def _async_retry_sources(self, _now: datetime) -> None:
        await self._async_load_sources()

    # -- state ----------------------------------------------------------------

    @property
    def available(self) -> bool:
        return not self.controller.speaker_unavailable

    @property
    def state(self) -> MediaPlayerState:
        speaker = self.controller.speaker_state
        if speaker is None or speaker.state == STATE_OFF:
            return MediaPlayerState.OFF
        if self.controller.is_ours:
            return _SPEAKER_STATES.get(speaker.state, MediaPlayerState.IDLE)
        return MediaPlayerState.IDLE

    @property
    def _speaker_attrs(self) -> dict[str, Any]:
        speaker = self.controller.speaker_state
        return dict(speaker.attributes) if speaker else {}

    @property
    def volume_level(self) -> float | None:
        return self._speaker_attrs.get(ATTR_MEDIA_VOLUME_LEVEL)

    @property
    def is_volume_muted(self) -> bool | None:
        return self._speaker_attrs.get(ATTR_MEDIA_VOLUME_MUTED)

    @property
    def media_content_type(self) -> MediaType | None:
        item = self.controller.current
        if item is None:
            return None
        return MediaType.MUSIC if item.is_live else MediaType.EPISODE

    @property
    def media_content_id(self) -> str | None:
        item = self.controller.current
        return item.ref if item else None

    @property
    def media_title(self) -> str | None:
        c = self.controller
        if c.current and c.current.is_live and c.program:
            return c.program.title
        return c.current.title if c.current else None

    @property
    def media_artist(self) -> str | None:
        item = self.controller.current
        return item.artist if item and not item.is_live else (item.title if item else None)

    @property
    def media_album_name(self) -> str | None:
        item = self.controller.current
        return item.artist if item and not item.is_live else None

    @property
    def media_channel(self) -> str | None:
        item = self.controller.current
        return item.title if item and item.is_live else None

    @property
    def media_image_url(self) -> str | None:
        c = self.controller
        if c.current and c.current.is_live and c.program and c.program.image:
            return c.program.image
        return c.current.image if c.current else None

    @property
    def media_duration(self) -> int | None:
        item = self.controller.current
        if item is None or item.is_live:
            return None
        return self._speaker_attrs.get(ATTR_MEDIA_DURATION) or item.episode.duration

    @property
    def media_position(self) -> float | None:
        if self.controller.is_ours and self.media_duration:
            return self._speaker_attrs.get(ATTR_MEDIA_POSITION)
        return None

    @property
    def media_position_updated_at(self) -> datetime | None:
        if self.controller.is_ours and self.media_duration:
            return self._speaker_attrs.get(ATTR_MEDIA_POSITION_UPDATED_AT)
        return None

    @property
    def source_list(self) -> list[str]:
        return list(self._sources)

    @property
    def source(self) -> str | None:
        item = self.controller.current
        if item is None:
            return None
        episode = item.episode
        ref = item.ref if item.is_live else (f"{episode.show_kind}/{episode.show_id}" if episode.show_kind else None)
        return next((name for name, src in self._sources.items() if src == ref), None)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.controller
        return {
            "speaker": c.speaker,
            "keep_playing": c.keep_playing,
            # The card marks rows by these ids: what's playing and what's queued.
            "queue": [{"id": i.ref, "title": i.title, "artist": i.artist} for i in c.queue],
            "queue_position": c.index if c.queue else None,
            "program_ends": c.program.end.isoformat() if c.program else None,
        }

    # -- commands -------------------------------------------------------------

    async def async_media_play(self) -> None:
        await self.controller.async_resume()

    async def async_media_pause(self) -> None:
        await self.controller.async_pause()

    async def async_media_stop(self) -> None:
        await self.controller.async_stop()

    async def async_media_next_track(self) -> None:
        await self.controller.async_next()

    async def async_media_previous_track(self) -> None:
        await self.controller.async_previous()

    async def async_media_seek(self, position: float) -> None:
        await self.controller.async_seek(position)

    async def async_set_volume_level(self, volume: float) -> None:
        await self.controller.async_volume("volume_set", volume_level=volume)

    async def async_mute_volume(self, mute: bool) -> None:
        await self.controller.async_volume("volume_mute", is_volume_muted=mute)

    async def async_volume_up(self) -> None:
        await self.controller.async_volume("volume_up")

    async def async_volume_down(self) -> None:
        await self.controller.async_volume("volume_down")

    async def async_clear_playlist(self) -> None:
        self.controller.clear_upcoming()

    async def async_remove_from_queue(self, position: int) -> None:
        self.controller.remove(position)

    async def async_select_source(self, source: str) -> None:
        if source not in self._sources:
            raise HomeAssistantError(f"Unknown source '{source}'")
        await self.controller.async_play(self._sources[source])

    async def async_play_media(
        self,
        media_type: MediaType | str,
        media_id: str,
        enqueue: MediaPlayerEnqueue | None = None,
        **kwargs: Any,
    ) -> None:
        """Play a media-source id from the browser, or a short form like
        'channel/p1', 'series/nyhetsmorgen', 'episode/podcast/<show>/<id>'.

        extra.speaker picks the speaker first (used by the episode card)."""
        speaker = (kwargs.get(ATTR_MEDIA_EXTRA) or {}).get("speaker")
        await self.controller.async_play(_strip_media_source(media_id), enqueue, speaker)

    async def async_browse_media(
        self, media_content_type: MediaType | str | None = None, media_content_id: str | None = None
    ) -> BrowseMedia:
        return await media_source.async_browse_media(
            self.hass, media_content_id or f"{media_source.URI_SCHEME}{DOMAIN}"
        )

    async def async_search_media(self, query: SearchMediaQuery) -> SearchMedia:
        return await media_source.async_search_media(
            self.hass, f"{media_source.URI_SCHEME}{DOMAIN}", query
        )
