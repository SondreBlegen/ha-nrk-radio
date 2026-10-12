"""The NRK library in Home Assistant's media browser.

Any speaker can play these directly (one item, no queue). The NRK Radio media
player browses the same tree but plays through its controller, which adds the
queue, "keep playing" and the episode card.
"""

from __future__ import annotations

import asyncio

from homeassistant.components.media_player import (
    BrowseError,
    MediaClass,
    MediaType,
    SearchMedia,
    SearchMediaQuery,
)
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import Item, NrkApi, NrkError, Show
from .const import (
    DOMAIN,
    KIND_CHANNEL,
    KIND_EPISODE,
    KIND_PAGE,
    KIND_PODCAST,
    KIND_PROGRAM,
    KIND_SECTION,
    KIND_SERIES,
)
from .controller import RadioController

EPISODES_SHOWN = 100

_CLASSES = {
    KIND_CHANNEL: (MediaClass.CHANNEL, MediaType.MUSIC, True, False),
    KIND_PODCAST: (MediaClass.PODCAST, MediaType.PODCAST, True, True),
    KIND_SERIES: (MediaClass.PODCAST, MediaType.PODCAST, True, True),
    KIND_EPISODE: (MediaClass.EPISODE, MediaType.EPISODE, True, False),
    KIND_PROGRAM: (MediaClass.EPISODE, MediaType.EPISODE, True, False),
    KIND_PAGE: (MediaClass.DIRECTORY, MediaType.MUSIC, False, True),
}


async def async_get_media_source(hass: HomeAssistant) -> NrkMediaSource:
    return NrkMediaSource(hass)


def _controller(hass: HomeAssistant) -> RadioController | None:
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return entry.runtime_data
    return None


def _folder(identifier: str, title: str, thumbnail: str | None = None) -> BrowseMediaSource:
    return BrowseMediaSource(
        domain=DOMAIN,
        identifier=identifier,
        media_class=MediaClass.DIRECTORY,
        media_content_type=MediaType.MUSIC,
        title=title,
        can_play=False,
        can_expand=True,
        thumbnail=thumbnail,
    )


def _node(item: Item) -> BrowseMediaSource:
    media_class, content_type, can_play, can_expand = _CLASSES[item.kind]
    title = item.title
    if item.subtitle and item.kind == KIND_EPISODE:
        title = f"{item.subtitle} · {title}"
    return BrowseMediaSource(
        domain=DOMAIN,
        identifier=item.ref,
        media_class=media_class,
        media_content_type=content_type,
        title=title,
        can_play=can_play,
        can_expand=can_expand,
        thumbnail=item.image,
    )


def _show_item(show: Show) -> Item:
    return Item(show.kind, f"{show.kind}/{show.id}", show.title, None, show.image)


class NrkMediaSource(MediaSource):
    name = "NRK Radio"

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(DOMAIN)
        self.hass = hass

    def _api(self) -> NrkApi:
        controller = _controller(self.hass)
        return controller.api if controller else NrkApi(async_get_clientsession(self.hass))

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        controller = _controller(self.hass)
        if controller is None:
            raise Unresolvable("NRK Radio is not set up")
        try:
            queue_item = await controller.async_resolve(item.identifier)
            if queue_item.is_live:
                stream = await controller.api.channel_stream(queue_item.channel_id)
            else:
                stream = await controller.api.episode_stream(queue_item.episode)
        except (NrkError, HomeAssistantError) as err:
            raise Unresolvable(str(err)) from err
        return PlayMedia(stream.url, stream.mime_type)

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        controller = _controller(self.hass)
        favourites = controller.favourite_shows if controller else []
        channels = controller.favourite_channels if controller else []
        try:
            return await browse(self._api(), item.identifier or "", favourites, channels)
        except NrkError as err:
            raise BrowseError(str(err)) from err

    async def async_search_media(self, item: MediaSourceItem, query: SearchMediaQuery) -> SearchMedia:
        try:
            hits = await self._api().search(query.search_query)
        except NrkError as err:
            raise BrowseError(str(err)) from err
        return SearchMedia(result=[_node(hit) for hit in hits])


async def browse(
    api: NrkApi, identifier: str, favourite_shows: list[str], favourite_channels: list[str]
) -> BrowseMediaSource:
    if identifier == "":
        root = _folder("", "NRK Radio")
        root.children = [_folder("favourites", "Mine favoritter"), _folder("channels", "Direkte")]
        root.children += [
            _node(Item(KIND_PAGE, f"page/{p.id}", p.title, None, p.image)) for p in await api.pages()
        ]
        return root

    if identifier == "favourites":
        folder = _folder(identifier, "Mine favoritter")
        shows = await asyncio.gather(
            *(api.show(*ref.split("/", 1)) for ref in favourite_shows), return_exceptions=True
        )
        folder.children = [_node(_show_item(s)) for s in shows if isinstance(s, Show)]
        return folder

    if identifier == "channels":
        folder = _folder(identifier, "Direkte")
        rank = {c: i for i, c in enumerate(favourite_channels)}
        channels = sorted(await api.channels(), key=lambda c: rank.get(c.id, len(rank)))
        folder.children = [
            _node(Item(KIND_CHANNEL, f"channel/{c.id}", c.title, None, c.image)) for c in channels
        ]
        return folder

    kind, _, rest = identifier.partition("/")

    if kind == KIND_PAGE:
        page = next((p for p in await api.pages() if p.id == rest), None)
        folder = _folder(identifier, page.title if page else rest, page.image if page else None)
        folder.children = [
            _folder(f"{KIND_SECTION}/{rest}/{n}", section.title or "Mer", section.items[0].image)
            for n, section in enumerate(await api.page(rest))
        ]
        return folder

    if kind == KIND_SECTION:
        page_id, _, number = rest.partition("/")
        sections = await api.page(page_id)
        try:
            section = sections[int(number)]
        except (ValueError, IndexError) as err:
            raise BrowseError(f"Unknown NRK section {identifier}") from err
        folder = _folder(identifier, section.title or "Mer")
        folder.children = [_node(item) for item in section.items]
        return folder

    if kind in (KIND_PODCAST, KIND_SERIES):
        show = await api.show(kind, rest)
        folder = _node(_show_item(show))
        folder.children_media_class = MediaClass.EPISODE
        folder.children = [
            BrowseMediaSource(
                domain=DOMAIN,
                identifier=f"{KIND_EPISODE}/{kind}/{rest}/{e.id}",
                media_class=MediaClass.EPISODE,
                media_content_type=MediaType.EPISODE,
                # Serials read best in story order; news by date.
                title=e.title if show.sequential or not e.date else f"{e.date:%d.%m.%y} · {e.title}",
                can_play=True,
                can_expand=False,
                thumbnail=e.image,
            )
            for e in await api.episodes(kind, rest, limit=EPISODES_SHOWN)
        ]
        return folder

    raise BrowseError(f"Unknown NRK item {identifier}")
