"""Client for NRK's public programme API (psapi.nrk.no), as radio.nrk.no uses it.

The library is made of *shows* (podcasts and radio series) holding *episodes*,
plus standalone *programs* and live *channels*. Category *pages* group these
into *sections*.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import logging
import time
from typing import Any

import aiohttp

from homeassistant.util import dt as dt_util

from .const import (
    API_BASE,
    KIND_CHANNEL,
    KIND_EPISODE,
    KIND_PAGE,
    KIND_PODCAST,
    KIND_PROGRAM,
    KIND_SERIES,
)

_LOGGER = logging.getLogger(__name__)

CHANNEL_CACHE_SECONDS = 6 * 3600
CATALOG_CACHE_SECONDS = 15 * 60
FRONT_PAGE = "direkte"
PAGE_SIZE = 50  # NRK answers 400 to anything larger
# Pages radio.nrk.no builds client-side; the API only has a placeholder section.
EMPTY_PAGES = {"alt-innhold"}


class NrkError(Exception):
    """NRK API request failed."""


@dataclass(frozen=True)
class Channel:
    id: str
    title: str
    image: str | None


@dataclass(frozen=True)
class Program:
    """What's on air right now on a live channel."""

    title: str
    image: str | None
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Show:
    kind: str  # KIND_PODCAST or KIND_SERIES
    id: str
    title: str
    image: str | None
    # Serialised shows (radio dramas, documentary series) are "sequential":
    # heard oldest-first. Everything else is newest-first.
    sequential: bool


@dataclass(frozen=True)
class Episode:
    show_kind: str | None  # None for a standalone program
    show_id: str | None
    id: str
    title: str
    show_title: str
    image: str | None
    duration: int | None = None
    date: datetime | None = None

    @property
    def is_podcast(self) -> bool:
        return self.show_kind == KIND_PODCAST


@dataclass(frozen=True)
class Item:
    """A browsable library entry: a page plug or a search hit.

    `ref` is the media identifier: "channel/p1", "series/nyhetsmorgen",
    "podcast/dagsnytt_atten", "episode/podcast/<show>/<id>", "program/<id>",
    "page/<id>".
    """

    kind: str
    ref: str
    title: str
    subtitle: str | None = None
    image: str | None = None


@dataclass(frozen=True)
class Page:
    id: str
    title: str
    image: str | None


@dataclass
class Section:
    title: str
    items: list[Item] = field(default_factory=list)


@dataclass(frozen=True)
class Stream:
    url: str
    mime_type: str
    live: bool


def _image(obj: Any, want: int = 600) -> str | None:
    """Pick the smallest image at least `want` px wide from any of NRK's image shapes."""
    if isinstance(obj, dict):
        obj = obj.get("webImages") or obj.get("images") or obj.get("items")
    if not isinstance(obj, list):
        return None
    sized = sorted(
        (i.get("width") or i.get("pixelWidth") or 0, i.get("url") or i.get("uri"))
        for i in obj
        if isinstance(i, dict) and (i.get("url") or i.get("uri"))
    )
    if not sized:
        return None
    return next((url for width, url in sized if width >= want), sized[-1][1])


def _tail(link: str) -> str:
    return link.rstrip("/").rsplit("/", 1)[-1]


def _seconds(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and (parsed := dt_util.parse_duration(value)):
        return int(parsed.total_seconds())
    return None


class NrkApi:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._cache: dict[str, tuple[float, Any]] = {}

    async def _get(self, path: str, **params: Any) -> Any:
        try:
            async with asyncio.timeout(15):
                resp = await self._session.get(
                    API_BASE + path, params=params or None, headers={"Accept": "application/json"}
                )
                if resp.status == 404:
                    raise NrkError(f"Not found: {path}")
                resp.raise_for_status()
                return await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise NrkError(f"{path}: {err}") from err

    async def _cached(self, key: str, ttl: float, fetch) -> Any:
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        value = await fetch()
        self._cache[key] = (time.monotonic(), value)
        return value

    # -- live radio -----------------------------------------------------------

    async def channels(self) -> list[Channel]:
        async def fetch() -> list[Channel]:
            channels = []
            for item in await self._get("/radio/live"):
                playback = item.get("_embedded", {}).get("playback", {})
                square = (playback.get("squarePosters") or [{}])[0]
                channels.append(
                    Channel(item["id"], playback.get("title") or item["id"], _image(square))
                )
            return channels

        return await self._cached("channels", CHANNEL_CACHE_SECONDS, fetch)

    async def now_playing(self, channel_id: str) -> Program | None:
        """The programme currently on air, from the channel's live buffer."""
        data = await self._get(f"/radio/channels/livebuffer/{channel_id}")
        now = dt_util.utcnow()
        for entry in data.get("channel", {}).get("entries", []):
            start = dt_util.parse_datetime(entry.get("actualStart") or "")
            end = dt_util.parse_datetime(entry.get("actualEnd") or "")
            if start and end and start <= now < end:
                image = entry.get("image") or {}
                return Program(
                    entry.get("title", ""),
                    _image(image.get("squareImage") or image.get("mainKeyArtImage")),
                    start,
                    end,
                )
        return None

    async def channel_stream(self, channel_id: str) -> Stream:
        return await self._manifest(f"/playback/manifest/channel/{channel_id}", live=True)

    # -- shows and episodes ---------------------------------------------------

    async def show(self, kind: str, show_id: str) -> Show:
        async def fetch() -> Show:
            data = await self._get(f"/radio/catalog/{kind}/{show_id}")
            series = data.get("series", {})
            return Show(
                kind=kind,
                id=show_id,
                title=series.get("titles", {}).get("title") or show_id,
                image=_image(series.get("squareImage")) or _image(series.get("image")),
                sequential=data.get("seriesType") == "sequential",
            )

        return await self._cached(f"show/{kind}/{show_id}", CATALOG_CACHE_SECONDS, fetch)

    async def find_show(self, show_id: str) -> Show:
        """Look an id up as a podcast first, then as a radio series."""
        try:
            return await self.show(KIND_PODCAST, show_id)
        except NrkError:
            return await self.show(KIND_SERIES, show_id)

    async def episodes(self, kind: str, show_id: str, limit: int = 50) -> list[Episode]:
        """Episodes in listening order: oldest-first for serials, else newest-first."""
        show = await self.show(kind, show_id)
        raw: list[dict[str, Any]] = []
        page = 1
        while len(raw) < limit:
            # Same page size on every request: NRK's page offset is page * size.
            data = await self._get(
                f"/radio/catalog/{kind}/{show_id}/episodes",
                page=page,
                pageSize=min(limit, PAGE_SIZE),
                sort="asc" if show.sequential else "desc",
            )
            raw += data.get("_embedded", {}).get("episodes", [])
            if not data.get("_links", {}).get("next"):
                break
            page += 1

        episodes = []
        for item in raw[:limit]:
            if item.get("availability", {}).get("status") not in (None, "available"):
                continue
            episodes.append(
                Episode(
                    show_kind=kind,
                    show_id=show_id,
                    id=item["episodeId"],
                    title=item.get("titles", {}).get("title") or show.title,
                    show_title=show.title,
                    image=_image(item.get("squareImage")) or _image(item.get("image")) or show.image,
                    duration=_seconds(item.get("durationInSeconds") or item.get("duration")),
                    date=dt_util.parse_datetime(item.get("date") or ""),
                )
            )
        return episodes

    async def program(self, program_id: str) -> Episode:
        """A standalone program (or any series episode) by its program id."""
        data = await self._get(f"/playback/metadata/program/{program_id}")
        preplay = data.get("preplay", {})
        title = preplay.get("titles", {}).get("title") or program_id
        return Episode(
            show_kind=None,
            show_id=None,
            id=program_id,
            title=title,
            show_title="NRK",
            image=_image(preplay.get("squarePoster")) or _image(preplay.get("poster")),
            duration=_seconds(data.get("duration")),
        )

    async def episode_stream(self, episode: Episode) -> Stream:
        if episode.is_podcast:
            return await self._manifest(f"/playback/manifest/podcast/{episode.id}", live=False)
        return await self._manifest(f"/playback/manifest/program/{episode.id}", live=False)

    # -- category pages -------------------------------------------------------

    async def pages(self) -> list[Page]:
        async def fetch() -> list[Page]:
            pages = [Page(FRONT_PAGE, "Forsiden", None)]
            for page in (await self._get("/radio/pages")).get("pages", []):
                if page["id"] in EMPTY_PAGES:
                    continue
                image = _image(page.get("imageSquare")) or _image(page.get("image"))
                pages.append(Page(page["id"], page.get("title") or page["id"], image))
            return pages

        return await self._cached("pages", CATALOG_CACHE_SECONDS, fetch)

    async def page(self, page_id: str) -> list[Section]:
        return await self._cached(
            f"page/{page_id}", CATALOG_CACHE_SECONDS, lambda: self._fetch_page(page_id)
        )

    async def _fetch_page(self, page_id: str) -> list[Section]:
        data = await self._get(f"/radio/pages/{page_id}")
        sections: list[Section] = []
        untitled: list[tuple[Section, int, str, str]] = []
        for raw in data.get("sections", []):
            included = raw.get("included", {})
            title = included.get("title") or ""
            # Editorial carousels are named "HERO 1", "HERO 2 DRAMA", ...
            if title.upper().startswith("HERO"):
                title = "Utvalgt"
            section = Section(title)
            for plug in included.get("plugs", []):
                item = self._plug(plug)
                if item is None:
                    continue
                if item.title is None:
                    kind, show_id = item.ref.split("/", 1)
                    untitled.append((section, len(section.items), kind, show_id))
                section.items.append(item)
            if section.items:
                sections.append(section)

        # Series plugs often carry only a description, so look their names up.
        if untitled:
            shows = await asyncio.gather(
                *(self.show(kind, show_id) for _, _, kind, show_id in untitled),
                return_exceptions=True,
            )
            for (section, index, _, show_id), show in zip(untitled, shows):
                old = section.items[index]
                name = show.title if isinstance(show, Show) else show_id
                section.items[index] = Item(old.kind, old.ref, name, old.subtitle, old.image)
        return sections

    @staticmethod
    def _plug(plug: dict[str, Any]) -> Item | None:
        kind = plug.get("type")
        links = plug.get("_links", {})
        body = plug.get(kind) or plug.get("program") or {}
        titles = body.get("titles", {})
        title, subtitle = titles.get("title"), titles.get("subtitle")
        image = body.get("imageUrl") or _image(body.get("image"))

        if kind == "podcast":
            # Podcast plugs keep the podcast's name in the subtitle.
            return Item(KIND_PODCAST, f"podcast/{_tail(links['podcast'])}", title or subtitle, None, image)
        if kind == "series":
            return Item(KIND_SERIES, f"series/{_tail(links['series'])}", title, subtitle, image)
        if kind == "podcastEpisode":
            show = _tail(links["podcast"])
            episode = _tail(links["podcastEpisode"])
            show_title = body.get("podcast", {}).get("titles", {}).get("title")
            return Item(KIND_EPISODE, f"episode/podcast/{show}/{episode}", title or subtitle, show_title, image)
        if kind == "episode":
            program = _tail(links["episode"])
            if series := links.get("series"):
                ref = f"episode/series/{_tail(series)}/{program}"
            else:
                ref = f"program/{program}"
            return Item(KIND_EPISODE, ref, title or subtitle, subtitle if title else None, image)
        if kind == "standaloneProgram":
            program = _tail(links["program"])
            return Item(KIND_PROGRAM, f"program/{program}", title or subtitle, None, image)
        if kind == "channel":
            return Item(KIND_CHANNEL, f"channel/{_tail(links['channel'])}", title, None, image)
        return None

    # -- search ---------------------------------------------------------------

    async def search(self, query: str, take: int = 15) -> list[Item]:
        data = await self._get("/radio/search/search", q=query, take=take)
        results = data.get("results", {})
        items: list[Item] = []

        def hits(group: str) -> list[dict[str, Any]]:
            return results.get(group, {}).get("results", [])

        def image(hit: dict[str, Any]) -> str | None:
            return _image(hit.get("images_1_1")) or _image(hit.get("images"))

        for hit in hits("series"):
            if hit.get("type") in (KIND_PODCAST, KIND_SERIES):
                items.append(
                    Item(hit["type"], f"{hit['type']}/{hit['seriesId']}", hit.get("title") or hit["seriesId"],
                         hit.get("description"), image(hit))
                )
        for hit in hits("channels"):
            items.append(Item(KIND_CHANNEL, f"channel/{hit['id']}", hit.get("title") or hit["id"], None, image(hit)))
        for hit in hits("episodes"):
            show_kind = {"podcastEpisode": KIND_PODCAST, "seriesEpisode": KIND_SERIES}.get(hit.get("type"))
            if show_kind and hit.get("seriesId"):
                ref = f"episode/{show_kind}/{hit['seriesId']}/{hit['episodeId']}"
            else:
                ref = f"program/{hit['episodeId']}"
            items.append(Item(KIND_EPISODE, ref, hit.get("title") or "", hit.get("seriesTitle"), image(hit)))
        for hit in hits("categories"):
            items.append(Item(KIND_PAGE, f"page/{hit['id']}", hit.get("title") or hit["id"], None, image(hit)))
        return items

    # -------------------------------------------------------------------------

    async def _manifest(self, path: str, live: bool) -> Stream:
        data = await self._get(path)
        if data.get("playability") != "playable":
            raise NrkError(f"{path} is not playable right now")
        assets = data.get("playable", {}).get("assets") or []
        if not assets:
            raise NrkError(f"{path} has no stream")
        asset = assets[0]
        return Stream(asset["url"], asset.get("mimeType") or "audio/mpeg", live)
