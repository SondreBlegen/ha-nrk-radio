"""Bridge between the card and Music Assistant.

HA's Music Assistant integration exposes players, but not what a card needs to
list a show's episodes, browse a provider or see the whole queue. These
websocket commands fill that gap through the client connection the integration
already holds, so any Music Assistant provider (NRK, Spotify, YouTube Music...)
works in the card the same way.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import datetime
from functools import wraps
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

MA_DOMAIN = "music_assistant"
EXPANDABLE = {"podcast", "album", "playlist", "artist", "folder"}
# A podcast's episode "position" is either an episode number (serials: show in
# story order) or, for dated shows, large enough to be a date (show newest first).
DATED_POSITION = 10_000


class BridgeError(Exception):
    """A request the bridge can't serve."""


def _client(hass: HomeAssistant) -> Any:
    for entry in hass.config_entries.async_loaded_entries(MA_DOMAIN):
        return entry.runtime_data.mass
    raise BridgeError("Music Assistant is not set up")


def _player_id(hass: HomeAssistant, entity_id: str) -> str:
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.platform != MA_DOMAIN:
        raise BridgeError(f"{entity_id} is not a Music Assistant player")
    return entry.unique_id  # the integration uses the MA player_id as unique id


async def _queue(hass: HomeAssistant, entity_id: str) -> Any:
    mass = _client(hass)
    queue = await mass.player_queues.get_active_queue(_player_id(hass, entity_id))
    if queue is None:
        raise BridgeError(f"{entity_id} has no queue")
    return queue


def _value(obj: Any) -> Any:
    return getattr(obj, "value", obj)


def _image(mass: Any, item: Any) -> str | None:
    try:
        return mass.get_media_item_image_url(item)
    except Exception:  # noqa: BLE001 - an image is never worth failing a listing
        return None


def _describe(mass: Any, item: Any) -> dict[str, Any]:
    """A media item, item mapping or browse folder, as the card wants it."""
    media_type = str(_value(getattr(item, "media_type", "folder")))
    folder = media_type == "folder" or not getattr(item, "uri", None)
    metadata = getattr(item, "metadata", None)
    date = getattr(metadata, "release_date", None) if metadata else None
    podcast = getattr(item, "podcast", None)
    artists = getattr(item, "artists", None) or []
    subtitle = None
    if isinstance(date, datetime):
        subtitle = date.strftime("%d.%m.%y")
    elif artists:
        subtitle = ", ".join(a.name for a in artists if getattr(a, "name", None))
    elif podcast is not None and getattr(podcast, "name", None):
        subtitle = podcast.name
    return {
        "uri": None if folder else item.uri,
        "path": getattr(item, "path", None) if folder else None,
        "name": item.name,
        "media_type": "folder" if folder else media_type,
        "image": _image(mass, item),
        "subtitle": subtitle,
        "duration": getattr(item, "duration", None),
        "can_expand": folder or media_type in EXPANDABLE,
        "can_play": not folder,
    }


async def _children(mass: Any, item: Any) -> list[Any]:
    media_type = str(_value(item.media_type))
    item_id, provider = item.item_id, item.provider
    if media_type == "podcast":
        episodes = await mass.music.get_podcast_episodes(item_id, provider)
        dated = any((e.position or 0) >= DATED_POSITION for e in episodes)
        return sorted(episodes, key=lambda e: e.position or 0, reverse=dated)
    if media_type == "album":
        return await mass.music.get_album_tracks(item_id, provider)
    if media_type == "playlist":
        return await mass.music.get_playlist_tracks(item_id, provider)
    if media_type == "artist":
        return await mass.music.get_artist_albums(item_id, provider)
    return []


def _handler(
    func: Callable[[HomeAssistant, dict[str, Any]], Coroutine[Any, Any, Any]],
) -> Callable:
    """Turn a coroutine into a websocket handler that reports bridge errors cleanly."""

    @wraps(func)
    async def wrapper(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
        try:
            result = await func(hass, msg)
        except BridgeError as err:
            connection.send_error(msg["id"], "not_available", str(err))
            return
        except Exception as err:  # noqa: BLE001 - surface MA errors to the card
            connection.send_error(msg["id"], "music_assistant_error", str(err))
            return
        connection.send_result(msg["id"], result)

    return websocket_api.async_response(wrapper)


@websocket_api.websocket_command(
    {vol.Required("type"): "nrk_radio/ma/item", vol.Optional("uri"): str, vol.Optional("path"): str}
)
@_handler
async def ws_item(hass: HomeAssistant, msg: dict) -> dict[str, Any]:
    """An item and what's inside it (episodes, tracks...), or a browse folder's contents."""
    mass = _client(hass)
    if uri := msg.get("uri"):
        item = await mass.music.get_item_by_uri(uri)
        children = await _children(mass, item)
        return {"item": _describe(mass, item), "children": [_describe(mass, c) for c in children]}
    path = msg.get("path")
    children = await mass.music.browse(path)
    name = path.rstrip("/").rsplit("/", 1)[-1] if path else "Music Assistant"
    return {
        "item": {"name": name, "media_type": "folder", "path": path, "image": None},
        "children": [_describe(mass, c) for c in children],
    }


@websocket_api.websocket_command({vol.Required("type"): "nrk_radio/ma/search", vol.Required("query"): str})
@_handler
async def ws_search(hass: HomeAssistant, msg: dict) -> dict[str, Any]:
    """Search every Music Assistant provider."""
    mass = _client(hass)
    results = await mass.music.search(msg["query"], limit=8)
    items: list[Any] = []
    for group in ("podcasts", "playlists", "albums", "artists", "radio", "tracks", "audiobooks"):
        items += getattr(results, group, None) or []
    return {"children": [_describe(mass, i) for i in items]}


@websocket_api.websocket_command({vol.Required("type"): "nrk_radio/ma/queue", vol.Required("entity_id"): str})
@_handler
async def ws_queue(hass: HomeAssistant, msg: dict) -> dict[str, Any]:
    """The player's queue: what's playing, what's next, and Autoplay."""
    mass = _client(hass)
    queue = await _queue(hass, msg["entity_id"])
    items = await mass.player_queues.get_queue_items(queue.queue_id, limit=200)
    autoplay = getattr(queue, "autoplay_enabled", None)
    if autoplay is None:
        autoplay = getattr(queue, "dont_stop_the_music_enabled", False)
    return {
        "queue_id": queue.queue_id,
        "state": str(_value(queue.state)),
        "current_index": queue.current_index,
        "autoplay": bool(autoplay),
        "items": [
            {
                "queue_item_id": qi.queue_item_id,
                "uri": qi.media_item.uri if qi.media_item else None,
                "name": qi.name,
            }
            for qi in items
        ],
    }


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nrk_radio/ma/play",
        vol.Required("entity_id"): str,
        vol.Required("uri"): str,
        vol.Optional("enqueue", default="replace"): vol.In(["replace", "add", "next", "play"]),
    }
)
@_handler
async def ws_play(hass: HomeAssistant, msg: dict) -> None:
    """Play now (replacing the queue) or add to it."""
    from music_assistant_models.enums import QueueOption  # noqa: PLC0415 - MA is optional

    mass = _client(hass)
    queue = await _queue(hass, msg["entity_id"])
    await mass.player_queues.play_media(queue.queue_id, msg["uri"], QueueOption(msg["enqueue"]))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nrk_radio/ma/remove",
        vol.Required("entity_id"): str,
        vol.Required("queue_item_id"): str,
    }
)
@_handler
async def ws_remove(hass: HomeAssistant, msg: dict) -> None:
    mass = _client(hass)
    queue = await _queue(hass, msg["entity_id"])
    await mass.player_queues.delete_item(queue.queue_id, msg["queue_item_id"])


@websocket_api.websocket_command({vol.Required("type"): "nrk_radio/ma/clear_upcoming", vol.Required("entity_id"): str})
@_handler
async def ws_clear_upcoming(hass: HomeAssistant, msg: dict) -> None:
    """Drop everything after the current item; what's playing keeps playing."""
    mass = _client(hass)
    queue = await _queue(hass, msg["entity_id"])
    items = await mass.player_queues.get_queue_items(queue.queue_id, limit=500)
    current = queue.current_index or 0
    for qi in items[current + 1 :]:
        await mass.player_queues.delete_item(queue.queue_id, qi.queue_item_id)


@websocket_api.websocket_command(
    {vol.Required("type"): "nrk_radio/ma/autoplay", vol.Required("entity_id"): str, vol.Required("enabled"): bool}
)
@_handler
async def ws_autoplay(hass: HomeAssistant, msg: dict) -> None:
    """Keep playing: Music Assistant's Autoplay ("don't stop the music")."""
    mass = _client(hass)
    queue = await _queue(hass, msg["entity_id"])
    await mass.player_queues.dont_stop_the_music(queue.queue_id, msg["enabled"])


@callback
def async_register(hass: HomeAssistant) -> None:
    for command in (ws_item, ws_search, ws_queue, ws_play, ws_remove, ws_clear_upcoming, ws_autoplay):
        websocket_api.async_register_command(hass, command)
