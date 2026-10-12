"""End-to-end behaviour of NRK Radio against a fake API and fake speakers."""

from __future__ import annotations

from datetime import timedelta

from homeassistant import config_entries
from homeassistant.components import media_source
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util

from custom_components.nrk_radio.api import Program
from custom_components.nrk_radio.const import CONF_SHOWS, DOMAIN

from .conftest import KITCHEN, LIVING

PLAYER = "media_player.nrk_radio"
KEEP = "switch.nrk_radio_keep_playing"


async def _service(hass: HomeAssistant, domain: str, service: str, **data) -> None:
    await hass.services.async_call(domain, service, data, blocking=True)
    await hass.async_block_till_done()


async def _play(hass: HomeAssistant, media_id: str, **extra) -> None:
    await _service(hass, "media_player", "play_media", entity_id=PLAYER,
                   media_content_type="music", media_content_id=media_id, **extra)


def _queue(hass: HomeAssistant) -> list[str]:
    return [item["id"] for item in hass.states.get(PLAYER).attributes["queue"]]


# -- setup --------------------------------------------------------------------


async def test_config_flow_resolves_show_links_and_ids(hass: HomeAssistant, nrk) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"speakers": [KITCHEN], "channels": ["p1"],
         "shows": ["https://radio.nrk.no/podkast/pod/l_123", "drama", "series/drama"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_SHOWS] == ["podcast/pod", "series/drama", "series/drama"]


async def test_config_flow_rejects_unknown_show(hass: HomeAssistant, nrk) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"speakers": [KITCHEN], "channels": ["p1"], "shows": ["nope"]}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SHOWS: "unknown_show"}


async def test_entities_created(hass: HomeAssistant, setup) -> None:
    assert hass.states.get(PLAYER).state == "idle"
    assert hass.states.get("select.nrk_radio_speaker").state == "Kitchen"
    assert hass.states.get(KEEP).state == "off"
    for button in ("nrk_p1", "nrk_p2", "pod", "drama"):
        assert hass.states.get(f"button.nrk_radio_{button}"), button
    assert hass.states.get(PLAYER).attributes["source_list"] == ["NRK P1", "NRK P2", "Pod", "Drama"]


# -- live radio ---------------------------------------------------------------


async def test_channel_button_casts_live_and_next_cycles_favourites(hass: HomeAssistant, setup, speakers) -> None:
    await _service(hass, "button", "press", entity_id="button.nrk_radio_nrk_p2")

    entity_id, service, data = speakers.calls[-1]
    assert (entity_id, service) == (KITCHEN, "play_media")
    assert data["media_content_id"] == "https://cdn/p2.m3u8"
    assert data["media_content_type"] == "application/vnd.apple.mpegurl"
    assert data["extra"]["stream_type"] == "LIVE"
    assert data["extra"]["media_info"] == {"hlsSegmentFormat": "ts"}

    state = hass.states.get(PLAYER)
    assert state.state == "playing"
    assert state.attributes["media_title"] == "Now on p2"
    assert state.attributes["media_channel"] == "NRK P2"
    assert state.attributes["source"] == "NRK P2"
    assert state.attributes["volume_level"] == 0.3

    await _service(hass, "media_player", "media_next_track", entity_id=PLAYER)  # wraps around
    assert speakers.played()[-1] == (KITCHEN, "https://cdn/p1.m3u8")
    await _service(hass, "media_player", "media_previous_track", entity_id=PLAYER)
    assert speakers.played()[-1] == (KITCHEN, "https://cdn/p2.m3u8")
    assert _queue(hass) == ["channel/p2"]


async def test_live_radio_replaces_even_when_enqueued(hass: HomeAssistant, setup, speakers) -> None:
    await _play(hass, "episode/podcast/pod/e1")
    await _play(hass, "channel/p3", enqueue="add")
    assert speakers.played()[-1] == (KITCHEN, "https://cdn/p3.m3u8")
    assert _queue(hass) == ["channel/p3"]


async def test_pause_and_resume_live_returns_to_live_edge(hass: HomeAssistant, setup, speakers) -> None:
    await _service(hass, "button", "press", entity_id="button.nrk_radio_nrk_p1")
    await _service(hass, "media_player", "media_pause", entity_id=PLAYER)
    assert hass.states.get(PLAYER).state == "paused"
    await _service(hass, "media_player", "media_play", entity_id=PLAYER)
    assert speakers.played() == [(KITCHEN, "https://cdn/p1.m3u8")] * 2


async def test_program_title_refreshes_when_programme_ends(hass: HomeAssistant, setup, speakers, nrk) -> None:
    await _service(hass, "button", "press", entity_id="button.nrk_radio_nrk_p1")
    controller = setup.runtime_data
    controller.program = Program("Old", None, dt_util.utcnow() - timedelta(hours=1), dt_util.utcnow())
    calls = nrk.call_count
    await controller._async_tick(dt_util.utcnow())
    await hass.async_block_till_done()
    assert nrk.call_count == calls + 1
    assert hass.states.get(PLAYER).attributes["media_title"] == "Now on p1"


async def test_someone_else_takes_the_speaker(hass: HomeAssistant, setup, speakers) -> None:
    await _service(hass, "button", "press", entity_id="button.nrk_radio_nrk_p1")
    speakers.set(KITCHEN, "playing", media_content_id="spotify:track:abc")
    await hass.async_block_till_done()
    assert hass.states.get(PLAYER).state == "idle"


# -- the library --------------------------------------------------------------


async def test_show_button_starts_first_episode_in_listening_order(hass: HomeAssistant, setup, speakers) -> None:
    await _service(hass, "button", "press", entity_id="button.nrk_radio_drama")
    assert speakers.played() == [(KITCHEN, "https://od/d1.m3u8")]
    _, _, data = speakers.calls[-1]
    assert data["extra"]["stream_type"] == "BUFFERED"
    assert data["extra"]["media_info"] == {"hlsSegmentFormat": "ts"}
    state = hass.states.get(PLAYER)
    assert state.attributes["media_title"] == "D episode 1"
    assert state.attributes["media_artist"] == "Drama"
    assert state.attributes["source"] == "Drama"
    assert _queue(hass) == ["episode/series/drama/d1"]


async def test_standalone_program_plays(hass: HomeAssistant, setup, speakers) -> None:
    await _play(hass, "media-source://nrk_radio/program/solo")
    assert speakers.played() == [(KITCHEN, "https://od/solo.m3u8")]
    assert hass.states.get(PLAYER).attributes["media_title"] == "Solo"


async def test_enqueue_adds_without_interrupting(hass: HomeAssistant, setup, speakers) -> None:
    await _play(hass, "media-source://nrk_radio/episode/podcast/pod/e1")
    await _play(hass, "media-source://nrk_radio/episode/series/drama/d2", enqueue="add")
    await _play(hass, "episode/podcast/pod/e3", enqueue="next")

    assert speakers.played() == [(KITCHEN, "https://pod/e1.mp3")]
    assert _queue(hass) == ["episode/podcast/pod/e1", "episode/podcast/pod/e3", "episode/series/drama/d2"]

    await _service(hass, "nrk_radio", "remove_from_queue", entity_id=PLAYER, position=1)
    assert _queue(hass) == ["episode/podcast/pod/e1", "episode/series/drama/d2"]
    await _service(hass, "media_player", "clear_playlist", entity_id=PLAYER)
    assert _queue(hass) == ["episode/podcast/pod/e1"]


async def test_enqueue_when_nothing_plays_starts_it(hass: HomeAssistant, setup, speakers) -> None:
    await _play(hass, "episode/podcast/pod/e1")
    speakers.finish()
    await hass.async_block_till_done()
    await _play(hass, "episode/podcast/pod/e2", enqueue="add")
    assert speakers.played()[-1] == (KITCHEN, "https://pod/e2.mp3")


async def test_queue_plays_through_then_stops(hass: HomeAssistant, setup, speakers) -> None:
    await _play(hass, "episode/series/drama/d1")
    await _play(hass, "episode/podcast/pod/e3", enqueue="add")

    speakers.finish()
    await hass.async_block_till_done()
    assert speakers.played()[-1] == (KITCHEN, "https://pod/e3.mp3")
    assert hass.states.get(PLAYER).attributes["queue_position"] == 1

    speakers.finish()
    await hass.async_block_till_done()
    assert len(speakers.played()) == 2  # keep playing is off: the queue ends here
    assert hass.states.get(PLAYER).state == "idle"


async def test_keep_playing_continues_with_the_show(hass: HomeAssistant, setup, speakers) -> None:
    await _service(hass, "switch", "turn_on", entity_id=KEEP)
    await _play(hass, "episode/series/drama/d1")
    speakers.finish()
    await hass.async_block_till_done()
    assert speakers.played()[-1] == (KITCHEN, "https://od/d2.m3u8")  # story order
    assert _queue(hass)[-1] == "episode/series/drama/d2"

    await _play(hass, "episode/podcast/pod/e3")  # the oldest: nothing after it
    speakers.finish()
    await hass.async_block_till_done()
    assert speakers.played()[-1] == (KITCHEN, "https://pod/e3.mp3")


async def test_stopping_mid_episode_does_not_advance(hass: HomeAssistant, setup, speakers) -> None:
    await _service(hass, "switch", "turn_on", entity_id=KEEP)
    await _play(hass, "episode/podcast/pod/e1")
    speakers.set(KITCHEN, "playing", media_position=100, media_position_updated_at=dt_util.utcnow())
    await hass.async_block_till_done()
    await _service(hass, "media_player", "media_stop", entity_id=PLAYER)
    speakers.set(KITCHEN, "idle")  # or stopped from the Google Home app
    await hass.async_block_till_done()
    assert speakers.played() == [(KITCHEN, "https://pod/e1.mp3")]


async def test_next_and_previous_walk_the_show(hass: HomeAssistant, setup, speakers) -> None:
    await _play(hass, "episode/series/drama/d2")
    await _service(hass, "media_player", "media_next_track", entity_id=PLAYER)
    assert speakers.played()[-1] == (KITCHEN, "https://od/d3.m3u8")

    speakers.set(KITCHEN, "playing", media_position=120, media_position_updated_at=dt_util.utcnow())
    await hass.async_block_till_done()
    await _service(hass, "media_player", "media_previous_track", entity_id=PLAYER)
    assert speakers.calls[-1][1:] == ("media_seek", {"seek_position": 0})

    speakers.set(KITCHEN, "playing", media_position=2, media_position_updated_at=dt_util.utcnow())
    await hass.async_block_till_done()
    await _service(hass, "media_player", "media_previous_track", entity_id=PLAYER)
    assert speakers.played()[-1] == (KITCHEN, "https://od/d2.m3u8")
    await _service(hass, "media_player", "media_previous_track", entity_id=PLAYER)
    assert speakers.played()[-1] == (KITCHEN, "https://od/d1.m3u8")


# -- speakers -----------------------------------------------------------------


async def test_switching_speaker_moves_playback(hass: HomeAssistant, setup, speakers) -> None:
    await _play(hass, "episode/podcast/pod/e1")
    speakers.set(KITCHEN, "playing", media_position=200, media_position_updated_at=dt_util.utcnow())
    await hass.async_block_till_done()

    await _service(hass, "select", "select_option", entity_id="select.nrk_radio_speaker", option="Living")

    assert (KITCHEN, "media_stop") in [(e, s) for e, s, _ in speakers.calls]
    entity_id, service, data = speakers.calls[-1]
    assert (entity_id, service) == (LIVING, "play_media")
    assert data["media_content_id"] == "https://pod/e1.mp3"
    assert 199 <= data["extra"]["current_time"] <= 205
    assert hass.states.get(PLAYER).attributes["speaker"] == LIVING
    assert hass.states.get(PLAYER).state == "playing"


async def test_card_speaker_replaces_without_moving(hass: HomeAssistant, setup, speakers) -> None:
    await _play(hass, "episode/podcast/pod/e1")
    await _play(hass, "episode/podcast/pod/e2", extra={"speaker": LIVING})
    assert speakers.played() == [(KITCHEN, "https://pod/e1.mp3"), (LIVING, "https://pod/e2.mp3")]
    assert hass.states.get("select.nrk_radio_speaker").state == "Living"


# -- browsing and search ------------------------------------------------------


async def test_browse_tree(hass: HomeAssistant, setup) -> None:
    root = await media_source.async_browse_media(hass, "media-source://nrk_radio")
    assert [c.title for c in root.children] == ["Mine favoritter", "Direkte", "Forsiden", "Kultur"]

    favourites = await media_source.async_browse_media(hass, "media-source://nrk_radio/favourites")
    assert [c.title for c in favourites.children] == ["Pod", "Drama"]

    channels = await media_source.async_browse_media(hass, "media-source://nrk_radio/channels")
    assert [c.title for c in channels.children] == ["NRK P1", "NRK P2", "NRK P3"]

    page = await media_source.async_browse_media(hass, "media-source://nrk_radio/page/direkte")
    assert [c.title for c in page.children] == ["Utvalgt"]  # empty sections are dropped

    section = await media_source.async_browse_media(hass, "media-source://nrk_radio/section/direkte/0")
    assert [(c.title, c.media_content_id.removeprefix("media-source://nrk_radio/")) for c in section.children] == [
        ("Drama", "series/drama"),  # name looked up, not the description
        ("Pod", "podcast/pod"),
        ("Pod · Second", "episode/podcast/pod/e2"),
        ("Part two", "episode/series/drama/d2"),
        ("Solo", "program/solo"),
        ("NRK P3", "channel/p3"),
    ]

    drama = await media_source.async_browse_media(hass, "media-source://nrk_radio/series/drama")
    assert [c.title for c in drama.children] == ["D episode 1", "D episode 2", "D episode 3"]
    assert drama.can_play and drama.can_expand
    pod = await media_source.async_browse_media(hass, "media-source://nrk_radio/podcast/pod")
    assert pod.children[0].title == "12.10.26 · E episode 1"  # news-style shows get dates


async def test_any_speaker_can_play_from_the_media_source(hass: HomeAssistant, setup) -> None:
    resolved = await media_source.async_resolve_media(hass, "media-source://nrk_radio/channel/p2", None)
    assert (resolved.url, resolved.mime_type) == ("https://cdn/p2.m3u8", "application/vnd.apple.mpegurl")
    resolved = await media_source.async_resolve_media(hass, "media-source://nrk_radio/series/drama", None)
    assert resolved.url == "https://od/d1.m3u8"


async def test_search(hass: HomeAssistant, setup, speakers) -> None:
    response = await hass.services.async_call(
        "media_player", "search_media", {"entity_id": PLAYER, "search_query": "drama"},
        blocking=True, return_response=True,
    )
    results = response[PLAYER].result
    assert [(r.title, r.media_content_id.removeprefix("media-source://nrk_radio/")) for r in results] == [
        ("Drama", "series/drama"),
        ("NRK P2", "channel/p2"),
        ("Pod · Third", "episode/podcast/pod/e3"),
        ("Kultur", "page/kultur"),
    ]
    # What Assist does with the first hit:
    await _play(hass, results[0].media_content_id)
    assert speakers.played() == [(KITCHEN, "https://od/d1.m3u8")]


async def test_episode_pages_stay_within_nrks_limit(hass: HomeAssistant, setup, nrk) -> None:
    """NRK answers 400 to pageSize > 50; longer lists must page."""
    await media_source.async_browse_media(hass, "media-source://nrk_radio/series/drama")
    sizes = [int(url.query["pageSize"]) for _, url, *_ in nrk.mock_calls if url.path.endswith("/episodes")]
    assert sizes and max(sizes) <= 50


async def test_card_is_served(hass: HomeAssistant, setup, hass_client) -> None:
    client = await hass_client()
    resp = await client.get("/nrk_radio/nrk-radio-card.js")
    assert resp.status == 200
    assert "customElements.define(\"nrk-radio-card\"" in await resp.text()


async def test_unload(hass: HomeAssistant, setup) -> None:
    assert await hass.config_entries.async_unload(setup.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(PLAYER).state == "unavailable"
