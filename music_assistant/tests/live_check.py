"""Exercise the NRK provider inside the real Music Assistant image, against live NRK.

    docker build -t nrk-ma-test -f music_assistant/tests/Dockerfile .
    docker run --rm nrk-ma-test

Only the bits of `mass` the provider touches are stubbed (cache, task creation,
HTTP session); models, base classes and NRK itself are real.
"""

import asyncio
from types import SimpleNamespace

import aiohttp
from music_assistant_models.enums import MediaType, StreamType

from music_assistant.providers.nrk_radio import SUPPORTED_FEATURES, NrkRadioProvider

FAILURES: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        FAILURES.append(what)


class NoCache:
    async def get_with_freshness(self, *args, **kwargs):
        return None, False, False

    async def set(self, *args, **kwargs):
        return None


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        mass = SimpleNamespace(
            cache=NoCache(),
            http_session=session,
            create_task=lambda coro, task_id=None, **kw: asyncio.ensure_future(coro),
        )
        manifest = SimpleNamespace(domain="nrk_radio")
        config = SimpleNamespace(instance_id="nrk_radio", name="NRK Radio", get_value=lambda key: None)
        prov = NrkRadioProvider(mass, manifest, config, SUPPORTED_FEATURES)

        print("browse")
        root = await prov.browse("nrk_radio://")
        names = [f.name for f in root]
        check(names[:2] == ["Direkte", "Forsiden"] and "Lyddrama" in names, f"root folders {names}")
        channels = await prov.browse("nrk_radio://channels")
        check(len(channels) > 20 and channels[0].media_type == MediaType.RADIO, f"{len(channels)} live channels")
        sections = await prov.browse("nrk_radio://page/hoerespill")
        check(len(sections) > 3, f"Lyddrama sections: {[s.name for s in sections[:4]]}")
        items = await prov.browse("nrk_radio://page/hoerespill/1")
        check(items and all(i.name for i in items), f"section items named: {[i.name for i in items[:3]]}")

        print("podcast (newest first)")
        pod = await prov.get_podcast("podcast:fantorangens_vitseshow")
        check(pod.name == "Fantorangens vitseshow" and bool(pod.metadata.images), f"podcast {pod.name}")
        eps = [e async for e in prov.get_podcast_episodes("podcast:fantorangens_vitseshow")]
        check(len(eps) >= 20, f"{len(eps)} episodes")
        check(eps[0].position > eps[-1].position, "newest has the highest position")
        check(eps[0].metadata.release_date is not None, f"release date {eps[0].metadata.release_date}")
        check(eps[0].duration > 60 and eps[0].podcast.item_id == pod.item_id, f"episode {eps[0].name} {eps[0].duration}s")
        one = await prov.get_podcast_episode(eps[3].item_id)
        check(one.item_id == eps[3].item_id and one.name == eps[3].name, f"get_podcast_episode {one.name}")
        sd = await prov.get_stream_details(eps[0].item_id, MediaType.PODCAST_EPISODE)
        check(sd.stream_type == StreamType.HTTP and sd.path.endswith(".mp3"), f"podcast stream {sd.stream_type} {sd.path[-30:]}")

        print("radio drama (story order)")
        drama = [e async for e in prov.get_podcast_episodes("series:doedens-budbaerer")]
        check([e.position for e in drama] == list(range(1, len(drama) + 1)), f"parts {[e.name for e in drama]}")
        sd = await prov.get_stream_details(drama[0].item_id, MediaType.PODCAST_EPISODE)
        check(sd.stream_type == StreamType.HLS and sd.can_seek, f"drama stream {sd.stream_type}")

        print("news series (100 newest, two pages)")
        news = [e async for e in prov.get_podcast_episodes("series:nyhetsmorgen")]
        check(90 <= len(news) <= 100 and len({e.item_id for e in news}) == len(news), f"{len(news)} unique episodes")

        print("live radio")
        radio = await prov.get_radio("p1_rogaland")
        check(radio.name == "NRK P1 Rogaland", f"radio {radio.name}")
        sd = await prov.get_stream_details("p1_rogaland", MediaType.RADIO)
        check(sd.stream_type == StreamType.HLS and not sd.can_seek, f"live stream {sd.stream_type}")

        print("standalone programme")
        prog = await prov.get_podcast_episode("program:KERA81000581")
        check(prog.name and prog.duration > 0, f"programme {prog.name} {prog.duration}s")
        progpod = await prov.get_podcast(prog.podcast.item_id)
        check(progpod.name == prog.name, "programme acts as a one-episode show")

        print("search")
        res = await prov.search("fantorangen", [MediaType.PODCAST, MediaType.RADIO], limit=5)
        check(any(p.item_id == "podcast:fantorangens_vitseshow" for p in res.podcasts), f"podcasts {[p.name for p in res.podcasts]}")
        res = await prov.search("p2", [MediaType.RADIO], limit=5)
        check(not res.podcasts and bool(res.radio), f"radio-only search {[r.name for r in res.radio]}")

    print("\nFAILED: " + ", ".join(FAILURES) if FAILURES else "\nall checks passed")
    raise SystemExit(1 if FAILURES else 0)


asyncio.run(main())
