"""Fixtures: a fake NRK API and fake speakers that react like Cast devices."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.nrk_radio.const import (
    API_BASE,
    CONF_CHANNELS,
    CONF_SHOWS,
    CONF_SPEAKERS,
    DOMAIN,
)
from custom_components.nrk_radio.controller import RadioController
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

pytest_plugins = "pytest_homeassistant_custom_component"

KITCHEN = "media_player.kitchen"
LIVING = "media_player.living"
EPISODE_LENGTH = 600


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def _playable(url: str, mime: str) -> dict[str, Any]:
    return {"playability": "playable", "playable": {"assets": [{"url": url, "mimeType": mime}]}}


def _channel(cid: str, title: str) -> dict[str, Any]:
    return {
        "id": cid,
        "_embedded": {
            "playback": {
                "title": title,
                "squarePosters": [{"items": [{"url": f"https://img/{cid}", "pixelWidth": 600}]}],
            }
        },
    }


def _episodes(prefix: str) -> dict[str, Any]:
    return {
        "_embedded": {
            "episodes": [
                {
                    "episodeId": f"{prefix}{i}",
                    "titles": {"title": f"{prefix.upper()} episode {i}"},
                    "durationInSeconds": EPISODE_LENGTH,
                    "date": "2026-10-12T19:00:00+02:00",
                    "availability": {"status": "available"},
                }
                for i in (1, 2, 3)
            ]
        }
    }


@pytest.fixture
def nrk(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    now = dt_util.utcnow()
    mock = aioclient_mock
    mock.get(
        f"{API_BASE}/radio/live",
        json=[_channel("p1", "NRK P1"), _channel("p2", "NRK P2"), _channel("p3", "NRK P3")],
    )
    for cid in ("p1", "p2", "p3"):
        mock.get(
            f"{API_BASE}/playback/manifest/channel/{cid}",
            json=_playable(f"https://cdn/{cid}.m3u8", "application/vnd.apple.mpegurl"),
        )
        mock.get(
            f"{API_BASE}/radio/channels/livebuffer/{cid}",
            json={
                "channel": {
                    "entries": [
                        {
                            "title": f"Now on {cid}",
                            "actualStart": (now - timedelta(minutes=5)).isoformat(),
                            "actualEnd": (now + timedelta(minutes=55)).isoformat(),
                        }
                    ]
                }
            },
        )

    # A podcast (MP3, newest first) and a radio drama (HLS, in story order).
    mock.get(f"{API_BASE}/radio/catalog/podcast/pod", json={"seriesType": "standard", "series": {"titles": {"title": "Pod"}}})
    mock.get(f"{API_BASE}/radio/catalog/podcast/pod/episodes", json=_episodes("e"))
    for i in (1, 2, 3):
        mock.get(f"{API_BASE}/playback/manifest/podcast/e{i}", json=_playable(f"https://pod/e{i}.mp3", "audio/mp3"))
    mock.get(f"{API_BASE}/radio/catalog/series/drama", json={"seriesType": "sequential", "series": {"titles": {"title": "Drama"}}})
    mock.get(f"{API_BASE}/radio/catalog/series/drama/episodes", json=_episodes("d"))
    for i in (1, 2, 3):
        mock.get(
            f"{API_BASE}/playback/manifest/program/d{i}",
            json=_playable(f"https://od/d{i}.m3u8", "application/vnd.apple.mpegurl"),
        )
    mock.get(
        f"{API_BASE}/playback/metadata/program/solo",
        json={"duration": "PT10M", "preplay": {"titles": {"title": "Solo"}}},
    )
    mock.get(f"{API_BASE}/playback/manifest/program/solo", json=_playable("https://od/solo.m3u8", "application/vnd.apple.mpegurl"))
    for kind, show in (("podcast", "drama"), ("podcast", "nope"), ("series", "nope"), ("series", "pod")):
        mock.get(f"{API_BASE}/radio/catalog/{kind}/{show}", status=404)

    mock.get(f"{API_BASE}/radio/pages", json={"pages": [{"id": "kultur", "title": "Kultur"}]})
    mock.get(f"{API_BASE}/radio/pages/kultur", json={"sections": []})
    mock.get(
        f"{API_BASE}/radio/pages/direkte",
        json={
            "sections": [
                {
                    "type": "included",
                    "included": {
                        "title": "HERO 1",
                        "plugs": [
                            # Series plugs often only have a description.
                            {"type": "series", "_links": {"series": "/series/drama"},
                             "series": {"titles": {"subtitle": "A thrilling story"}}},
                            {"type": "podcast", "_links": {"podcast": "/podcasts/pod"},
                             "podcast": {"titles": {"subtitle": "Pod"}, "imageUrl": "https://img/pod"}},
                            {"type": "podcastEpisode",
                             "_links": {"podcast": "/podcasts/pod", "podcastEpisode": "/podcasts/pod/episodes/e2"},
                             "podcastEpisode": {"titles": {"title": "Second"}, "podcast": {"titles": {"title": "Pod"}}}},
                            {"type": "episode",
                             "_links": {"episode": "/programs/d2", "series": "/series/drama"},
                             "episode": {"titles": {"title": "Part two"}}},
                            {"type": "standaloneProgram", "_links": {"program": "/programs/solo"},
                             "program": {"titles": {"title": "Solo"}}},
                            {"type": "channel", "_links": {"channel": "/mediaelement/p3"},
                             "channel": {"titles": {"title": "NRK P3"}}},
                            {"type": "somethingNew", "_links": {}},
                        ],
                    },
                },
                {"type": "included", "included": {"title": "Empty section", "plugs": []}},
            ]
        },
    )
    mock.get(
        f"{API_BASE}/radio/search/search",
        json={
            "results": {
                "series": {"results": [
                    {"type": "series", "seriesId": "drama", "title": "Drama"},
                    {"type": "customSeason", "seriesId": "x", "title": "Skipped"},
                ]},
                "episodes": {"results": [
                    {"type": "podcastEpisode", "seriesId": "pod", "episodeId": "e3", "title": "Third", "seriesTitle": "Pod"},
                ]},
                "channels": {"results": [{"id": "p2", "title": "NRK P2"}]},
                "categories": {"results": [{"id": "kultur", "title": "Kultur"}]},
            }
        },
    )
    return mock


class FakeSpeakers:
    """Records commands and updates the speaker's state like Cast would."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        for entity_id, name in ((KITCHEN, "Kitchen"), (LIVING, "Living")):
            hass.states.async_set(entity_id, "idle", {"friendly_name": name, "volume_level": 0.3})

    def set(self, entity_id: str, state: str, **attrs: Any) -> None:
        current = dict(self.hass.states.get(entity_id).attributes)
        current.update(attrs)
        self.hass.states.async_set(entity_id, state, current)

    async def __call__(self, controller: RadioController, service: str, **data: Any) -> None:
        entity_id = controller.speaker
        self.calls.append((entity_id, service, data))
        if service == "play_media":
            live = data["extra"]["stream_type"] == "LIVE"
            self.set(
                entity_id,
                "playing",
                media_content_id=data["media_content_id"],
                media_position=data["extra"].get("current_time", 0),
                media_position_updated_at=dt_util.utcnow(),
                media_duration=None if live else EPISODE_LENGTH,
            )
        elif service == "media_stop":
            self.idle(entity_id)
        elif service == "media_pause":
            self.set(entity_id, "paused")
        elif service == "media_play":
            self.set(entity_id, "playing")

    def played(self) -> list[tuple[str, str]]:
        return [(e, d["media_content_id"]) for e, s, d in self.calls if s == "play_media"]

    def idle(self, entity_id: str = KITCHEN) -> None:
        """Go idle the way Cast does: it still reports a position, reset to 0."""
        self.set(entity_id, "idle", media_position=0, media_position_updated_at=dt_util.utcnow())

    def finish(self, entity_id: str = KITCHEN, played_from_start: bool = False) -> None:
        """Run the current episode to its end.

        played_from_start: Cast sent no position update since the episode
        began (what real Cast does), so only elapsed time says it's done.
        """
        if played_from_start:
            self.set(entity_id, "playing", media_position=0,
                     media_position_updated_at=dt_util.utcnow() - timedelta(seconds=EPISODE_LENGTH))
        else:
            self.set(entity_id, "playing", media_position=EPISODE_LENGTH - 2,
                     media_position_updated_at=dt_util.utcnow())
        self.idle(entity_id)


@pytest.fixture
def speakers(hass: HomeAssistant):
    fake = FakeSpeakers(hass)

    async def speaker_call(controller: RadioController, service: str, **data: Any) -> None:
        await fake(controller, service, **data)

    with patch.object(RadioController, "_speaker_call", new=speaker_call):
        yield fake


@pytest.fixture
async def setup(hass: HomeAssistant, nrk, speakers) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="NRK Radio",
        options={
            CONF_SPEAKERS: [KITCHEN, LIVING],
            CONF_CHANNELS: ["p1", "p2"],
            CONF_SHOWS: ["podcast/pod", "series/drama"],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
