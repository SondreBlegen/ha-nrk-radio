"""Capture real NRK browse/search responses through the integration's own code,
as fixtures for the card harness (tests/card/harness.html).

    docker run --rm nrk-radio-run python tests/card/capture.py > tests/card/fixtures.json
"""

import asyncio
import json

import aiohttp

from custom_components.nrk_radio.api import NrkApi
from custom_components.nrk_radio.media_source import _node, browse

PREFIX = "media-source://nrk_radio"
BROWSE = ["", "favourites", "series/nyhetsmorgen", "series/doedens-budbaerer", "podcast/dagsnytt_atten", "page/hoerespill", "section/hoerespill/1"]
FAVOURITES = ["podcast/dagsnytt_atten", "series/nyhetsmorgen", "series/doedens-budbaerer"]


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        api = NrkApi(session)
        out = {"browse": {}, "search": {}}
        for ident in BROWSE:
            node = await browse(api, ident, FAVOURITES, ["p1", "p2"])
            out["browse"][f"{PREFIX}/{ident}".rstrip("/")] = node.as_dict()
        hits = await api.search("krim")
        out["search"]["krim"] = {"version": 1, "result": [_node(h).as_dict(parent=False) for h in hits]}
        print(json.dumps(out, ensure_ascii=False))


asyncio.run(main())
