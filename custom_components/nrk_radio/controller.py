"""Playback controller: owns the queue and drives the chosen speaker.

The NRK media player, the speaker select, the keep-playing switch and the
buttons are all thin views over this one object, so they can never disagree
about what is playing.

Queue model: playing something replaces the queue; enqueueing appends to it.
When the queue runs out, playback stops, unless "keep playing" is on, in
which case it carries on with the next episode of the same show.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.media_player import (
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_DURATION,
    ATTR_MEDIA_POSITION,
    ATTR_MEDIA_POSITION_UPDATED_AT,
    DOMAIN as MP_DOMAIN,
    SERVICE_PLAY_MEDIA,
    MediaPlayerEnqueue,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_BUFFERING,
    STATE_IDLE,
    STATE_OFF,
    STATE_PAUSED,
    STATE_PLAYING,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util

from .api import Channel, Episode, NrkApi, NrkError, Program
from .const import KIND_CHANNEL, KIND_EPISODE, KIND_PODCAST, KIND_PROGRAM, KIND_SERIES

_LOGGER = logging.getLogger(__name__)

# Cast's default media receiver: MusicTrackMediaMetadata
_CAST_MUSIC_METADATA = 3
# How many episodes of a show we look through to find "the next one".
_SHOW_WINDOW = 100
# Only these report a position that means anything; idle resets it to 0.
_PROGRESS_STATES = (STATE_PLAYING, STATE_PAUSED, STATE_BUFFERING)


@dataclass(frozen=True)
class QueueItem:
    ref: str  # media identifier, e.g. "channel/p1" or "episode/series/x/ID"
    title: str
    artist: str
    image: str | None
    channel_id: str | None = None
    episode: Episode | None = None

    @property
    def is_live(self) -> bool:
        return self.channel_id is not None

    @classmethod
    def from_channel(cls, channel: Channel) -> QueueItem:
        return cls(f"{KIND_CHANNEL}/{channel.id}", channel.title, "NRK", channel.image, channel_id=channel.id)

    @classmethod
    def from_episode(cls, episode: Episode) -> QueueItem:
        if episode.show_kind:
            ref = f"{KIND_EPISODE}/{episode.show_kind}/{episode.show_id}/{episode.id}"
        else:
            ref = f"{KIND_PROGRAM}/{episode.id}"
        return cls(ref, episode.title, episode.show_title, episode.image, episode=episode)


class RadioController:
    """Single source of truth for what NRK is playing, and where."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: NrkApi,
        speakers: list[str],
        favourite_channels: list[str],
        favourite_shows: list[str],
    ) -> None:
        self.hass = hass
        self.api = api
        self.speakers = speakers
        self.favourite_channels = favourite_channels
        self.favourite_shows = favourite_shows

        self.speaker: str | None = speakers[0] if speakers else None
        self.keep_playing = False
        self.queue: list[QueueItem] = []
        self.index = 0
        self.program: Program | None = None

        # The URL we last handed the speaker. If the speaker reports a different
        # content id, someone else (Spotify, the Google Home app...) took over.
        self._sent_url: str | None = None
        # (position, updated_at, duration) of our stream, for auto-advance.
        self._last_progress: tuple[float, datetime, float] | None = None

        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._unsub_speaker: CALLBACK_TYPE | None = None

    # -- lifecycle ------------------------------------------------------------

    async def async_start(self) -> None:
        self.track_speaker()
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._async_tick, timedelta(seconds=30), cancel_on_shutdown=True
            )
        )

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._unsub_speaker:
            self._unsub_speaker()
            self._unsub_speaker = None

    @callback
    def add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # -- state ----------------------------------------------------------------

    @property
    def current(self) -> QueueItem | None:
        if 0 <= self.index < len(self.queue):
            return self.queue[self.index]
        return None

    @property
    def upcoming(self) -> list[QueueItem]:
        return self.queue[self.index + 1 :]

    @property
    def speaker_state(self) -> State | None:
        return self.hass.states.get(self.speaker) if self.speaker else None

    @property
    def speaker_unavailable(self) -> bool:
        state = self.speaker_state
        return state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)

    @property
    def is_ours(self) -> bool:
        """True while the speaker is playing the stream we sent it."""
        state = self.speaker_state
        return bool(
            state
            and self._sent_url
            and state.attributes.get(ATTR_MEDIA_CONTENT_ID) == self._sent_url
        )

    @property
    def is_active(self) -> bool:
        """Something of ours is loaded on the speaker (playing, paused or buffering)."""
        state = self.speaker_state
        return self.is_ours and state is not None and state.state not in (STATE_IDLE, STATE_OFF)

    # -- resolving identifiers ------------------------------------------------

    async def async_resolve(self, ref: str) -> QueueItem:
        """Turn a media identifier into something playable."""
        kind, _, rest = ref.partition("/")
        try:
            if kind == KIND_CHANNEL:
                channel = next((c for c in await self.api.channels() if c.id == rest), None)
                if channel is None:
                    raise HomeAssistantError(f"NRK has no channel '{rest}'")
                return QueueItem.from_channel(channel)
            if kind in (KIND_PODCAST, KIND_SERIES):
                episodes = await self.api.episodes(kind, rest, limit=1)
                if not episodes:
                    raise HomeAssistantError(f"'{rest}' has no playable episodes")
                return QueueItem.from_episode(episodes[0])
            if kind == KIND_EPISODE:
                show_kind, _, rest = rest.partition("/")
                show_id, _, episode_id = rest.partition("/")
                return QueueItem.from_episode(await self._episode(show_kind, show_id, episode_id))
            if kind == KIND_PROGRAM:
                return QueueItem.from_episode(await self.api.program(rest))
        except NrkError as err:
            raise HomeAssistantError(f"Could not load {ref} from NRK: {err}") from err
        raise HomeAssistantError(f"Don't know how to play '{ref}'")

    async def _episode(self, show_kind: str, show_id: str, episode_id: str) -> Episode:
        for episode in await self.api.episodes(show_kind, show_id, limit=_SHOW_WINDOW):
            if episode.id == episode_id:
                return episode
        # Older than we page through: borrow the show's name, keep the link to it.
        show = await self.api.show(show_kind, show_id)
        title = show.title
        if show_kind == KIND_SERIES:
            title = (await self.api.program(episode_id)).title
        return Episode(show_kind, show_id, episode_id, title, show.title, show.image)

    # -- queue and playback ---------------------------------------------------

    async def async_play(
        self, ref: str, enqueue: MediaPlayerEnqueue | None = None, speaker: str | None = None
    ) -> None:
        item = await self.async_resolve(ref)
        # Live radio never ends, so it can't wait in a queue: it always replaces.
        replace = item.is_live or not self.queue or enqueue in (None, MediaPlayerEnqueue.REPLACE)

        if speaker and speaker != self.speaker:
            if speaker not in self.speakers:
                raise HomeAssistantError(f"{speaker} is not one of NRK Radio's speakers")
            # Queueing takes the current playback along; replacing just stops it.
            await self.async_set_speaker(speaker, move=not replace)

        if replace:
            self.queue = [item]
            await self.async_play_index(0)
            return
        if enqueue == MediaPlayerEnqueue.ADD:
            self.queue.append(item)
        else:  # NEXT or PLAY
            self.queue.insert(self.index + 1, item)
        if enqueue == MediaPlayerEnqueue.PLAY or not self.is_active or self.current.is_live:
            await self.async_play_index(self.index + 1)
        else:
            self.notify()

    @callback
    def clear_upcoming(self) -> None:
        del self.queue[self.index + 1 :]
        self.notify()

    @callback
    def remove(self, position: int) -> None:
        """Drop an upcoming item; the one playing stays."""
        if position > self.index and position < len(self.queue):
            del self.queue[position]
            self.notify()

    async def async_play_index(self, index: int, start_at: float | None = None) -> None:
        if not self.speaker:
            raise HomeAssistantError("No speaker selected")
        self.index = index
        item = self.queue[index]
        try:
            if item.is_live:
                stream = await self.api.channel_stream(item.channel_id)
            else:
                stream = await self.api.episode_stream(item.episode)
        except NrkError as err:
            raise HomeAssistantError(f"Could not start {item.title}: {err}") from err

        self.program = None
        self._last_progress = None
        self._sent_url = stream.url
        self.notify()

        extra: dict[str, Any] = {
            "stream_type": "LIVE" if stream.live else "BUFFERED",
            "metadata": {
                "metadataType": _CAST_MUSIC_METADATA,
                "title": item.title,
                "artist": item.artist,
                "images": [{"url": item.image}] if item.image else [],
            },
        }
        if "mpegurl" in stream.mime_type.lower():
            # NRK's HLS is audio-only MPEG-TS; Cast assumes packed AAC otherwise.
            extra["media_info"] = {"hlsSegmentFormat": "ts"}
        if start_at:
            extra["current_time"] = start_at

        await self._speaker_call(
            SERVICE_PLAY_MEDIA,
            media_content_id=stream.url,
            media_content_type=stream.mime_type,
            extra=extra,
        )
        if item.is_live:
            await self._async_refresh_program()

    async def async_next(self) -> None:
        item = self.current
        if item is None:
            return
        if self.index + 1 < len(self.queue):
            await self.async_play_index(self.index + 1)
        elif item.is_live:
            await self._async_step_channel(+1)
        elif following := await self._neighbour(item, +1):
            # Skipping forward past the queue continues the show, toggle or not.
            self.queue.append(QueueItem.from_episode(following))
            await self.async_play_index(self.index + 1)

    async def async_previous(self) -> None:
        item = self.current
        if item is None:
            return
        if item.is_live:
            await self._async_step_channel(-1)
            return
        position = self.estimated_position()
        if position is not None and position > 10:
            await self._speaker_call("media_seek", seek_position=0)
        elif self.index > 0:
            await self.async_play_index(self.index - 1)
        elif earlier := await self._neighbour(item, -1):
            self.queue.insert(0, QueueItem.from_episode(earlier))
            await self.async_play_index(0)
        else:
            await self._speaker_call("media_seek", seek_position=0)

    async def _async_step_channel(self, step: int) -> None:
        channels = {c.id: c for c in await self.api.channels()}
        ids = [c for c in self.favourite_channels if c in channels]
        current = self.current.channel_id if self.current else None
        if current not in ids:
            ids.insert(0, current)
        channel = channels.get(ids[(ids.index(current) + step) % len(ids)])
        if channel is None:
            return
        self.queue[self.index] = QueueItem.from_channel(channel)
        await self.async_play_index(self.index)

    async def _neighbour(self, item: QueueItem, step: int) -> Episode | None:
        """The episode before/after this one in its show's listening order."""
        episode = item.episode
        if episode is None or not episode.show_kind:
            return None
        try:
            episodes = await self.api.episodes(episode.show_kind, episode.show_id, limit=_SHOW_WINDOW)
        except NrkError as err:
            _LOGGER.warning("Could not load %s to find the next episode: %s", episode.show_id, err)
            return None
        ids = [e.id for e in episodes]
        if episode.id not in ids:
            return None
        position = ids.index(episode.id) + step
        return episodes[position] if 0 <= position < len(episodes) else None

    async def async_resume(self) -> None:
        item = self.current
        state = self.speaker_state
        if item is None:
            if self.favourite_channels:
                await self.async_play(f"{KIND_CHANNEL}/{self.favourite_channels[0]}")
            elif self.favourite_shows:
                await self.async_play(self.favourite_shows[0])
            else:
                raise HomeAssistantError("Nothing to play — pick something in the media browser")
        elif self.is_ours and not item.is_live and state and state.state != STATE_IDLE:
            await self._speaker_call("media_play")
        else:
            # Live radio resumes at the live edge, not where it was paused.
            await self.async_play_index(self.index)

    async def async_pause(self) -> None:
        if self.is_ours:
            await self._speaker_call("media_pause")

    async def async_stop(self) -> None:
        if self.is_ours:
            # Forget progress first, so the stop isn't mistaken for the end.
            self._last_progress = None
            await self._speaker_call("media_stop")

    async def async_seek(self, position: float) -> None:
        if self.is_ours:
            await self._speaker_call("media_seek", seek_position=position)

    async def async_volume(self, service: str, **data: Any) -> None:
        await self._speaker_call(service, **data)

    async def async_set_speaker(self, entity_id: str, move: bool = True) -> None:
        """Switch speaker, by default taking whatever is playing along with it."""
        if entity_id == self.speaker:
            return
        was_playing = self.is_ours and self.speaker_state.state == STATE_PLAYING
        position = self.estimated_position()
        if was_playing:
            await self.async_stop()
        self.speaker = entity_id
        self._sent_url = None
        self.track_speaker()
        if was_playing and move:
            resume = None if self.current.is_live else position
            await self.async_play_index(self.index, start_at=resume)
        self.notify()

    @callback
    def set_keep_playing(self, value: bool) -> None:
        self.keep_playing = value
        self.notify()

    async def _speaker_call(self, service: str, **data: Any) -> None:
        if not self.speaker:
            raise HomeAssistantError("No speaker selected")
        await self.hass.services.async_call(
            MP_DOMAIN, service, {ATTR_ENTITY_ID: self.speaker, **data}, blocking=True
        )

    # -- progress tracking ----------------------------------------------------

    def estimated_position(self) -> float | None:
        if not self._last_progress:
            return None
        position, updated_at, _ = self._last_progress
        state = self.speaker_state
        if state and state.state == STATE_PLAYING:
            position += (dt_util.utcnow() - updated_at).total_seconds()
        return position

    @callback
    def track_speaker(self) -> None:
        if self._unsub_speaker:
            self._unsub_speaker()
            self._unsub_speaker = None
        if self.speaker:
            self._unsub_speaker = async_track_state_change_event(
                self.hass, [self.speaker], self._async_speaker_changed
            )

    @callback
    def _async_speaker_changed(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        # Judge the end before taking anything from the new state: once idle,
        # Cast reports the position reset to 0, which would read as "stopped".
        if (
            old is not None
            and new is not None
            and old.state == STATE_PLAYING
            and new.state in (STATE_IDLE, STATE_OFF)
            and self._episode_finished(old)
        ):
            self.hass.async_create_task(self._async_advance(), "nrk_radio advance")
        elif (
            new is not None
            and new.state in _PROGRESS_STATES
            and self._sent_url
            and new.attributes.get(ATTR_MEDIA_CONTENT_ID) == self._sent_url
        ):
            position = new.attributes.get(ATTR_MEDIA_POSITION)
            updated_at = new.attributes.get(ATTR_MEDIA_POSITION_UPDATED_AT)
            if position is not None and updated_at is not None:
                self._last_progress = (
                    float(position),
                    updated_at,
                    float(new.attributes.get(ATTR_MEDIA_DURATION) or 0),
                )
        self.notify()

    def _episode_finished(self, old: State) -> bool:
        """Did the episode run out, as opposed to someone pressing stop?"""
        item = self.current
        if (
            item is None
            or item.is_live
            or old.attributes.get(ATTR_MEDIA_CONTENT_ID) != self._sent_url
            or not self._last_progress
        ):
            return False
        position, updated_at, duration = self._last_progress
        duration = duration or float(item.episode.duration or 0)
        if not duration:
            return False
        position += (dt_util.utcnow() - updated_at).total_seconds()
        return position >= duration - max(15.0, min(60.0, duration / 50))

    async def _async_advance(self) -> None:
        if self.index + 1 < len(self.queue):
            await self.async_play_index(self.index + 1)
        elif self.keep_playing and (following := await self._neighbour(self.current, +1)):
            self.queue.append(QueueItem.from_episode(following))
            await self.async_play_index(self.index + 1)
        else:
            _LOGGER.debug("Queue finished")
            self.notify()

    # -- now playing for live radio -------------------------------------------

    async def _async_tick(self, _now: datetime) -> None:
        item = self.current
        if item is None or not item.is_live or not self.is_ours:
            return
        if self.program is None or dt_util.utcnow() >= self.program.end:
            await self._async_refresh_program()

    async def _async_refresh_program(self) -> None:
        item = self.current
        if item is None or not item.is_live:
            return
        try:
            self.program = await self.api.now_playing(item.channel_id)
        except NrkError as err:
            _LOGGER.debug("Could not fetch what's on %s: %s", item.channel_id, err)
            return
        self.notify()
