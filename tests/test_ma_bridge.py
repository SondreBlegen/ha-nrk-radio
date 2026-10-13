"""The card's Music Assistant bridge, against a fake MA client with the real API shape."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace as NS

from music_assistant_models.enums import QueueOption
import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from pytest_homeassistant_custom_component.common import MockConfigEntry

PLAYER = "media_player.kids_speaker"
SHOW = "nrk_radio://podcast/podcast:vits"
DRAMA = "nrk_radio://podcast/series:drama"


def _episode(show: str, n: int, position: int, dated: bool) -> NS:
    return NS(
        uri=f"nrk_radio://podcast_episode/{show}:{n}",
        name=f"Episode {n}",
        media_type="podcast_episode",
        position=position,
        duration=600,
        metadata=NS(release_date=datetime(2026, 9, n, tzinfo=timezone.utc) if dated else None),
        podcast=NS(name=show),
        image_url=f"https://img/{show}/{n}",
    )


class FakeMass:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.queue = NS(queue_id="q1", state="playing", current_index=0, autoplay_enabled=False)
        self.items = [
            NS(queue_item_id="a", name="Episode 3", media_item=NS(uri="nrk_radio://podcast_episode/vits:3")),
            NS(queue_item_id="b", name="Episode 1", media_item=NS(uri="nrk_radio://podcast_episode/vits:1")),
            NS(queue_item_id="c", name="Episode 2", media_item=NS(uri="nrk_radio://podcast_episode/vits:2")),
        ]
        shows = {
            SHOW: NS(uri=SHOW, name="Vitseshow", media_type="podcast", item_id="podcast:vits",
                     provider="nrk_radio", metadata=NS(release_date=None), image_url="https://img/vits"),
            DRAMA: NS(uri=DRAMA, name="Drama", media_type="podcast", item_id="series:drama",
                      provider="nrk_radio", metadata=NS(release_date=None), image_url=None),
        }
        episodes = {
            # dated show: positions are dates, newest highest
            "podcast:vits": [_episode("vits", n, 202609000000 + n, True) for n in (1, 2, 3)],
            # serial: positions are part numbers
            "series:drama": [_episode("drama", n, n, False) for n in (2, 1, 3)],
        }

        async def get_item_by_uri(uri):
            return shows[uri]

        async def get_podcast_episodes(item_id, provider):
            assert provider == "nrk_radio"
            return list(episodes[item_id])

        async def browse(path):
            return [NS(name="Direkte", path="nrk_radio://channels", media_type="folder", uri=None)]

        async def search(query, limit=50):
            return NS(podcasts=[shows[SHOW]], radio=[], tracks=[])

        async def get_active_queue(player_id):
            assert player_id == "ma_player_kids"
            return self.queue

        async def get_queue_items(queue_id, limit=500, offset=0):
            return list(self.items)

        async def record(name, *args):
            self.calls.append((name, *args))

        self.music = NS(get_item_by_uri=get_item_by_uri, get_podcast_episodes=get_podcast_episodes,
                        browse=browse, search=search)
        self.player_queues = NS(
            get_active_queue=get_active_queue,
            get_queue_items=get_queue_items,
            play_media=lambda *a: record("play_media", *a),
            delete_item=lambda *a: record("delete_item", *a),
            dont_stop_the_music=lambda *a: record("dont_stop_the_music", *a),
        )

    def get_media_item_image_url(self, item):
        return getattr(item, "image_url", None)


@pytest.fixture
async def mass(hass: HomeAssistant) -> FakeMass:
    fake = FakeMass()
    entry = MockConfigEntry(domain="music_assistant", title="Music Assistant")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = NS(mass=fake)
    er.async_get(hass).async_get_or_create(
        "media_player", "music_assistant", "ma_player_kids", suggested_object_id="kids_speaker"
    )
    assert await async_setup_component(hass, "nrk_radio", {})
    await hass.async_block_till_done()
    return fake


async def _ws(hass, hass_ws_client, **msg):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(msg)
    return await client.receive_json()


async def test_dated_show_lists_newest_first(hass: HomeAssistant, mass, hass_ws_client) -> None:
    res = await _ws(hass, hass_ws_client, type="nrk_radio/ma/item", uri=SHOW)
    assert res["success"], res
    assert res["result"]["item"]["name"] == "Vitseshow"
    assert res["result"]["item"]["image"] == "https://img/vits"
    rows = res["result"]["children"]
    assert [r["name"] for r in rows] == ["Episode 3", "Episode 2", "Episode 1"]
    assert rows[0]["subtitle"] == "03.09.26"
    assert rows[0]["can_play"] and not rows[0]["can_expand"]


async def test_serial_lists_in_story_order(hass: HomeAssistant, mass, hass_ws_client) -> None:
    res = await _ws(hass, hass_ws_client, type="nrk_radio/ma/item", uri=DRAMA)
    assert [r["name"] for r in res["result"]["children"]] == ["Episode 1", "Episode 2", "Episode 3"]


async def test_browse_and_search(hass: HomeAssistant, mass, hass_ws_client) -> None:
    res = await _ws(hass, hass_ws_client, type="nrk_radio/ma/item", path="nrk_radio://")
    folder = res["result"]["children"][0]
    assert folder["media_type"] == "folder" and folder["path"] == "nrk_radio://channels"
    assert folder["can_expand"] and not folder["can_play"]
    res = await _ws(hass, hass_ws_client, type="nrk_radio/ma/search", query="vits")
    assert [r["uri"] for r in res["result"]["children"]] == [SHOW]


async def test_queue_play_remove_autoplay(hass: HomeAssistant, mass, hass_ws_client) -> None:
    res = await _ws(hass, hass_ws_client, type="nrk_radio/ma/queue", entity_id=PLAYER)
    assert res["result"]["current_index"] == 0 and res["result"]["autoplay"] is False
    assert [i["uri"] for i in res["result"]["items"]][1] == "nrk_radio://podcast_episode/vits:1"

    uri = "nrk_radio://podcast_episode/vits:2"
    await _ws(hass, hass_ws_client, type="nrk_radio/ma/play", entity_id=PLAYER, uri=uri, enqueue="add")
    await _ws(hass, hass_ws_client, type="nrk_radio/ma/play", entity_id=PLAYER, uri=uri)
    assert mass.calls[-2:] == [("play_media", "q1", uri, QueueOption.ADD),
                               ("play_media", "q1", uri, QueueOption.REPLACE)]

    await _ws(hass, hass_ws_client, type="nrk_radio/ma/remove", entity_id=PLAYER, queue_item_id="b")
    assert mass.calls[-1] == ("delete_item", "q1", "b")

    mass.calls.clear()
    await _ws(hass, hass_ws_client, type="nrk_radio/ma/clear_upcoming", entity_id=PLAYER)
    assert mass.calls == [("delete_item", "q1", "b"), ("delete_item", "q1", "c")]  # "a" plays on

    await _ws(hass, hass_ws_client, type="nrk_radio/ma/autoplay", entity_id=PLAYER, enabled=True)
    assert mass.calls[-1] == ("dont_stop_the_music", "q1", True)


async def test_rejects_players_that_are_not_music_assistant(hass: HomeAssistant, mass, hass_ws_client) -> None:
    res = await _ws(hass, hass_ws_client, type="nrk_radio/ma/queue", entity_id="media_player.kitchen")
    assert not res["success"] and res["error"]["code"] == "not_available"
