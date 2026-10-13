"""NRK Radio music provider: NRK's live channels and on-demand radio library.

Everything comes from psapi.nrk.no, the open API radio.nrk.no itself uses.

Mapping onto Music Assistant's models:
- live channels           -> Radio            item_id "p1_rogaland"
- podcasts                -> Podcast          item_id "podcast:dagsnytt_atten"
- radio series / dramas   -> Podcast          item_id "series:doedens-budbaerer"
- episodes of either      -> PodcastEpisode   item_id "<kind>:<show>:<episode>"
- standalone programmes   -> PodcastEpisode   item_id "program:<id>" (a one-episode show)

Episode positions decide what Autoplay plays next: serials (radio dramas) count up
in story order; everything else is numbered by date, so the next one is newer.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence
from datetime import datetime
import re
from typing import TYPE_CHECKING, Any, Final

import aiohttp
from music_assistant_models.enums import (
    ContentType,
    ImageType,
    MediaType,
    ProviderFeature,
    StreamType,
)
from music_assistant_models.errors import (
    MediaNotFoundError,
    ProviderUnavailableError,
    UnplayableMediaError,
)
from music_assistant_models.media_items import (
    AudioFormat,
    BrowseFolder,
    ItemMapping,
    MediaItemImage,
    MediaItemType,
    Podcast,
    PodcastEpisode,
    ProviderMapping,
    Radio,
    SearchResults,
)
from music_assistant_models.streamdetails import StreamDetails

from music_assistant.controllers.cache import use_cache
from music_assistant.models.music_provider import MusicProvider

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ConfigEntry, ProviderConfig
    from music_assistant_models.provider import ProviderManifest

    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType

API_BASE: Final = "https://psapi.nrk.no"
HTTP_TIMEOUT: Final = aiohttp.ClientTimeout(total=15)
PAGE_SIZE: Final = 50  # NRK answers 400 to anything larger
# News shows have thousands of episodes; nobody browses past the newest few pages.
EPISODES_STANDARD: Final = 100
EPISODES_SERIAL: Final = 500
FRONT_PAGE: Final = "direkte"
# Pages radio.nrk.no builds client-side; the API only has a placeholder section.
EMPTY_PAGES: Final = {"alt-innhold"}

PODCAST: Final = "podcast"
SERIES: Final = "series"
PROGRAM: Final = "program"

SUPPORTED_FEATURES = {ProviderFeature.BROWSE, ProviderFeature.SEARCH}


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    """Initialize provider instance."""
    return NrkRadioProvider(mass, manifest, config, SUPPORTED_FEATURES)


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


def _seconds(value: Any) -> int:
    """NRK durations come as seconds or ISO 8601 ("PT33M26S")."""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and (m := re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?", value)):
        hours, minutes, seconds = m.groups()
        return int(hours or 0) * 3600 + int(minutes or 0) * 60 + int(float(seconds or 0))
    return 0


def _parse_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class NrkRadioProvider(MusicProvider):
    """NRK Radio music provider."""

    @property
    def max_concurrent_streams(self) -> None:
        """Allow unlimited concurrent upstream streams (public CDN)."""
        return None

    async def get_config_entries(self) -> tuple[ConfigEntry, ...]:
        """No configuration needed: the API is open."""
        return ()

    # -- HTTP -----------------------------------------------------------------

    @use_cache(600)
    async def _get_json(self, path: str, **params: Any) -> Any:
        """GET a psapi.nrk.no path (raw JSON, cached briefly)."""
        try:
            async with self.mass.http_session.get(
                API_BASE + path,
                params={k: str(v) for k, v in params.items()} or None,
                headers={"Accept": "application/json"},
                timeout=HTTP_TIMEOUT,
            ) as resp:
                if resp.status == 404:
                    raise MediaNotFoundError(f"NRK has nothing at {path}")
                resp.raise_for_status()
                return await resp.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise ProviderUnavailableError(f"NRK API unavailable ({path}): {err}") from err

    def _add_image(self, item: Any, url: str | None) -> None:
        if url:
            item.metadata.add_image(
                MediaItemImage(
                    type=ImageType.THUMB, path=url, provider=self.domain, remotely_accessible=True
                )
            )

    def _mapping(self, item_id: str) -> set[ProviderMapping]:
        return {
            ProviderMapping(
                item_id=item_id, provider_domain=self.domain, provider_instance=self.instance_id
            )
        }

    # -- live radio -----------------------------------------------------------

    async def _channels(self) -> list[dict[str, Any]]:
        data = await self._get_json("/radio/live")
        return data if isinstance(data, list) else []

    def _radio(self, channel_id: str, title: str, image: str | None) -> Radio:
        radio = Radio(
            item_id=channel_id,
            provider=self.instance_id,
            name=title,
            provider_mappings=self._mapping(channel_id),
        )
        self._add_image(radio, image)
        return radio

    def _radio_from_live(self, item: dict[str, Any]) -> Radio:
        playback = item.get("_embedded", {}).get("playback", {})
        square = (playback.get("squarePosters") or [{}])[0]
        return self._radio(item["id"], playback.get("title") or item["id"], _image(square))

    async def get_radio(self, prov_radio_id: str) -> Radio:
        """Get a live channel by id."""
        for item in await self._channels():
            if item.get("id") == prov_radio_id:
                return self._radio_from_live(item)
        raise MediaNotFoundError(f"NRK channel {prov_radio_id} not found")

    # -- shows ----------------------------------------------------------------

    async def _show(self, kind: str, show_id: str) -> dict[str, Any]:
        return await self._get_json(f"/radio/catalog/{kind}/{show_id}")

    async def get_podcast(self, prov_podcast_id: str) -> Podcast:
        """Get a podcast or radio series (or a standalone programme) by id."""
        kind, _, show_id = prov_podcast_id.partition(":")
        if kind == PROGRAM:
            episode = await self._program_episode(show_id)
            podcast = Podcast(
                item_id=prov_podcast_id,
                provider=self.instance_id,
                name=episode.name,
                publisher="NRK",
                total_episodes=1,
                provider_mappings=self._mapping(prov_podcast_id),
            )
            for image in episode.metadata.images or []:
                podcast.metadata.add_image(image)
            return podcast
        if kind not in (PODCAST, SERIES):
            raise MediaNotFoundError(f"Unknown NRK show {prov_podcast_id}")
        data = await self._show(kind, show_id)
        series = data.get("series", {})
        titles = series.get("titles", {})
        podcast = Podcast(
            item_id=prov_podcast_id,
            provider=self.instance_id,
            name=titles.get("title") or show_id,
            publisher="NRK",
            provider_mappings=self._mapping(prov_podcast_id),
        )
        podcast.metadata.description = titles.get("subtitle")
        self._add_image(podcast, _image(series.get("squareImage")) or _image(series.get("image")))
        return podcast

    async def get_podcast_episodes(self, prov_podcast_id: str) -> AsyncGenerator[PodcastEpisode]:
        """Episodes of a show, numbered so Autoplay continues in the right direction."""
        kind, _, show_id = prov_podcast_id.partition(":")
        if kind == PROGRAM:
            yield await self._program_episode(show_id)
            return
        for episode in await self._episodes(kind, show_id):
            yield episode

    async def _episodes(self, kind: str, show_id: str) -> list[PodcastEpisode]:
        show = await self._show(kind, show_id)
        sequential = show.get("seriesType") == "sequential"
        show_title = show.get("series", {}).get("titles", {}).get("title") or show_id
        show_image = _image(show.get("series", {}).get("squareImage")) or _image(
            show.get("series", {}).get("image")
        )
        limit = EPISODES_SERIAL if sequential else EPISODES_STANDARD
        raw: list[dict[str, Any]] = []
        page = 1
        while len(raw) < limit:
            # NRK's page offset is (page - 1) * size, so keep the size fixed.
            data = await self._get_json(
                f"/radio/catalog/{kind}/{show_id}/episodes",
                page=page,
                pageSize=PAGE_SIZE,
                sort="asc" if sequential else "desc",
            )
            raw += data.get("_embedded", {}).get("episodes", [])
            if not data.get("_links", {}).get("next"):
                break
            page += 1

        episodes = []
        for index, item in enumerate(raw[:limit]):
            if item.get("availability", {}).get("status") not in (None, "available"):
                continue
            date = _parse_date(item.get("date"))
            if sequential or date is None:
                position = index + 1 if sequential else limit - index
            else:
                # Newer is higher: Autoplay moves on to the next newer episode.
                position = int(date.strftime("%Y%m%d%H%M"))
            episodes.append(
                self._episode(
                    kind,
                    show_id,
                    show_title,
                    item["episodeId"],
                    item.get("titles", {}).get("title") or show_title,
                    position,
                    _seconds(item.get("durationInSeconds") or item.get("duration")),
                    _image(item.get("squareImage")) or _image(item.get("image")) or show_image,
                    item.get("titles", {}).get("subtitle"),
                    date,
                )
            )
        return episodes

    def _episode(
        self,
        kind: str,
        show_id: str,
        show_title: str,
        episode_id: str,
        title: str,
        position: int,
        duration: int,
        image: str | None,
        description: str | None = None,
        date: datetime | None = None,
    ) -> PodcastEpisode:
        item_id = f"{kind}:{show_id}:{episode_id}" if kind != PROGRAM else f"{PROGRAM}:{episode_id}"
        podcast_id = f"{kind}:{show_id}" if kind != PROGRAM else item_id
        episode = PodcastEpisode(
            item_id=item_id,
            provider=self.instance_id,
            name=title,
            position=position,
            duration=duration,
            podcast=ItemMapping(
                item_id=podcast_id,
                provider=self.instance_id,
                name=show_title,
                media_type=MediaType.PODCAST,
            ),
            provider_mappings=self._mapping(item_id),
        )
        if description:
            episode.metadata.description = description
        if date:
            episode.metadata.release_date = date
        self._add_image(episode, image)
        return episode

    async def _program_episode(self, program_id: str) -> PodcastEpisode:
        data = await self._get_json(f"/playback/metadata/program/{program_id}")
        preplay = data.get("preplay", {})
        title = preplay.get("titles", {}).get("title") or program_id
        return self._episode(
            PROGRAM,
            program_id,
            title,
            program_id,
            title,
            1,
            _seconds(data.get("duration")),
            _image(preplay.get("squarePoster")) or _image(preplay.get("poster")),
            preplay.get("titles", {}).get("subtitle"),
        )

    async def get_podcast_episode(self, prov_episode_id: str) -> PodcastEpisode:
        """Get one episode by id."""
        parts = prov_episode_id.split(":")
        if parts[0] == PROGRAM and len(parts) == 2:
            return await self._program_episode(parts[1])
        if len(parts) != 3 or parts[0] not in (PODCAST, SERIES):
            raise MediaNotFoundError(f"Unknown NRK episode {prov_episode_id}")
        kind, show_id, episode_id = parts
        for episode in await self._episodes(kind, show_id):
            if episode.item_id == prov_episode_id:
                return episode
        # Older than we page through: build it from its playback metadata.
        meta_path = (
            f"/playback/metadata/podcast/{show_id}/{episode_id}"
            if kind == PODCAST
            else f"/playback/metadata/program/{episode_id}"
        )
        data = await self._get_json(meta_path)
        show = await self.get_podcast(f"{kind}:{show_id}")
        preplay = data.get("preplay", {})
        return self._episode(
            kind,
            show_id,
            show.name,
            episode_id,
            preplay.get("titles", {}).get("title") or show.name,
            0,
            _seconds(data.get("duration")),
            _image(preplay.get("squarePoster")) or _image(preplay.get("poster")),
        )

    # -- streams --------------------------------------------------------------

    async def get_stream_details(self, item_id: str, media_type: MediaType) -> StreamDetails:
        """Resolve a channel or episode to its NRK stream."""
        if media_type == MediaType.RADIO:
            path, live = f"/playback/manifest/channel/{item_id}", True
        elif media_type == MediaType.PODCAST_EPISODE:
            parts = item_id.split(":")
            if parts[0] == PODCAST and len(parts) == 3:
                path = f"/playback/manifest/podcast/{parts[2]}"
            else:
                path = f"/playback/manifest/program/{parts[-1]}"
            live = False
        else:
            raise UnplayableMediaError(f"NRK can't play {media_type}")

        # Manifests carry short-lived CDN URLs: never cached.
        try:
            async with self.mass.http_session.get(
                API_BASE + path, headers={"Accept": "application/json"}, timeout=HTTP_TIMEOUT
            ) as resp:
                resp.raise_for_status()
                manifest = await resp.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise UnplayableMediaError(f"NRK stream unavailable: {err}") from err
        if manifest.get("playability") != "playable":
            raise UnplayableMediaError(f"{item_id} is not playable right now")
        assets = manifest.get("playable", {}).get("assets") or []
        if not assets:
            raise UnplayableMediaError(f"{item_id} has no stream")
        asset = assets[0]
        hls = "mpegurl" in (asset.get("mimeType") or "").lower() or asset.get("format") == "HLS"
        return StreamDetails(
            provider=self.instance_id,
            item_id=item_id,
            media_type=media_type,
            stream_type=StreamType.HLS if hls else StreamType.HTTP,
            path=asset["url"],
            audio_format=AudioFormat(content_type=ContentType.AAC if hls else ContentType.MP3),
            can_seek=not live,
            allow_seek=not live,
        )

    # -- browse ---------------------------------------------------------------

    async def browse(self, path: str) -> Sequence[MediaItemType | ItemMapping | BrowseFolder]:
        """Live channels, then NRK's own category pages and their sections."""
        subpath = path.split("://", 1)[1] if "://" in path else ""
        if subpath == "":
            folders = [self._folder("channels", "Direkte")]
            for page in await self._pages():
                folders.append(self._folder(f"page/{page['id']}", page["title"]))
            return folders
        if subpath == "channels":
            return [self._radio_from_live(item) for item in await self._channels()]
        parts = subpath.split("/")
        if parts[0] == "page" and len(parts) == 2:
            return [
                self._folder(f"page/{parts[1]}/{n}", title)
                for n, (title, _) in enumerate(await self._page(parts[1]))
            ]
        if parts[0] == "page" and len(parts) == 3:
            sections = await self._page(parts[1])
            try:
                return sections[int(parts[2])][1]
            except (ValueError, IndexError) as err:
                raise MediaNotFoundError(f"Unknown NRK section {subpath}") from err
        raise MediaNotFoundError(f"Unknown NRK path {path}")

    def _folder(self, subpath: str, name: str) -> BrowseFolder:
        return BrowseFolder(
            item_id=subpath,
            provider=self.instance_id,
            path=f"{self.instance_id}://{subpath}",
            name=name,
        )

    async def _pages(self) -> list[dict[str, str]]:
        data = await self._get_json("/radio/pages")
        pages = [{"id": FRONT_PAGE, "title": "Forsiden"}]
        for page in data.get("pages", []):
            if page["id"] not in EMPTY_PAGES:
                pages.append({"id": page["id"], "title": page.get("title") or page["id"]})
        return pages

    async def _page(self, page_id: str) -> list[tuple[str, list[MediaItemType]]]:
        data = await self._get_json(f"/radio/pages/{page_id}")
        sections: list[tuple[str, list[MediaItemType]]] = []
        untitled: list[tuple[list[MediaItemType], int, str]] = []
        for raw in data.get("sections", []):
            included = raw.get("included", {})
            title = included.get("title") or ""
            if title.upper().startswith("HERO"):  # editorial carousels: "HERO 1", "HERO 2 DRAMA"
                title = "Utvalgt"
            items: list[MediaItemType] = []
            for plug in included.get("plugs", []):
                try:
                    item = self._plug(plug)
                except KeyError:
                    continue  # a plug shape we don't know
                if item is None:
                    continue
                if item.name == "":
                    untitled.append((items, len(items), item.item_id))
                items.append(item)
            if items:
                sections.append((title or "Mer", items))
        # Series plugs often carry only a description, so look their names up.
        if untitled:
            shows = await asyncio.gather(
                *(self.get_podcast(item_id) for _, _, item_id in untitled), return_exceptions=True
            )
            for (items, index, _), show in zip(untitled, shows):
                if isinstance(show, Podcast):
                    items[index] = show
        return sections

    def _plug(self, plug: dict[str, Any]) -> MediaItemType | None:
        kind = plug.get("type")
        links = plug.get("_links", {})
        body = plug.get(kind) or plug.get("program") or {}
        titles = body.get("titles", {})
        title, subtitle = titles.get("title"), titles.get("subtitle")
        image = body.get("imageUrl") or _image(body.get("image"))

        if kind in ("podcast", "series"):
            show_kind = PODCAST if kind == "podcast" else SERIES
            show_id = _tail(links[kind])
            # Podcast plugs keep the name in the subtitle; series plugs only a description.
            name = title or (subtitle if kind == "podcast" else "")
            podcast = Podcast(
                item_id=f"{show_kind}:{show_id}",
                provider=self.instance_id,
                name=name or "",
                publisher="NRK",
                provider_mappings=self._mapping(f"{show_kind}:{show_id}"),
            )
            self._add_image(podcast, image)
            return podcast
        if kind == "podcastEpisode":
            show_title = body.get("podcast", {}).get("titles", {}).get("title") or ""
            return self._episode(
                PODCAST, _tail(links["podcast"]), show_title, _tail(links["podcastEpisode"]),
                title or subtitle or show_title, 0, _seconds(body.get("duration")), image,
            )
        if kind == "episode":
            program = _tail(links["episode"])
            if series := links.get("series"):
                return self._episode(
                    SERIES, _tail(series), subtitle or "", program, title or subtitle or program,
                    0, _seconds(body.get("duration")), image,
                )
            return self._episode(
                PROGRAM, program, title or program, program, title or program, 1,
                _seconds(body.get("duration")), image,
            )
        if kind == "standaloneProgram":
            program = _tail(links["program"])
            name = title or subtitle or program
            return self._episode(
                PROGRAM, program, name, program, name, 1, _seconds(body.get("duration")), image
            )
        if kind == "channel":
            return self._radio(_tail(links["channel"]), title or _tail(links["channel"]), image)
        return None

    # -- search ---------------------------------------------------------------

    async def search(
        self, search_query: str, media_types: list[MediaType], limit: int = 5
    ) -> SearchResults:
        """Search NRK's library: shows, channels and episodes."""
        data = await self._get_json("/radio/search/search", q=search_query, take=max(limit, 10))
        results = data.get("results", {})
        out = SearchResults()

        def hits(group: str) -> list[dict[str, Any]]:
            return results.get(group, {}).get("results", [])

        def image(hit: dict[str, Any]) -> str | None:
            return _image(hit.get("images_1_1")) or _image(hit.get("images"))

        if not media_types or MediaType.PODCAST in media_types:
            podcasts = []
            for hit in hits("series"):
                if hit.get("type") not in (PODCAST, SERIES):
                    continue  # e.g. "customSeason": a curated slice of another show
                item_id = f"{hit['type']}:{hit['seriesId']}"
                podcast = Podcast(
                    item_id=item_id,
                    provider=self.instance_id,
                    name=hit.get("title") or hit["seriesId"],
                    publisher="NRK",
                    provider_mappings=self._mapping(item_id),
                )
                podcast.metadata.description = hit.get("description")
                self._add_image(podcast, image(hit))
                podcasts.append(podcast)
            out.podcasts = podcasts[:limit]
        if not media_types or MediaType.RADIO in media_types:
            out.radio = [
                self._radio(hit["id"], hit.get("title") or hit["id"], image(hit))
                for hit in hits("channels")
            ][:limit]
        if (not media_types or MediaType.PODCAST_EPISODE in media_types) and hasattr(
            out, "podcast_episodes"
        ):
            episodes = []
            for hit in hits("episodes"):
                kind = {"podcastEpisode": PODCAST, "seriesEpisode": SERIES}.get(hit.get("type"))
                if not kind or not hit.get("seriesId"):
                    continue
                episodes.append(
                    self._episode(
                        kind, hit["seriesId"], hit.get("seriesTitle") or "", hit["episodeId"],
                        hit.get("title") or "", 0, 0, image(hit),
                    )
                )
            out.podcast_episodes = episodes[:limit]
        return out
