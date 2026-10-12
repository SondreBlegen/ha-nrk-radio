"""Constants for NRK Radio."""

DOMAIN = "nrk_radio"

API_BASE = "https://psapi.nrk.no"

CONF_SPEAKERS = "speakers"
CONF_CHANNELS = "channels"
CONF_SHOWS = "shows"

# Regional P1 editions (p1_rogaland, p1_hordaland, ...) can be picked in setup.
DEFAULT_CHANNELS = [
    "p1",
    "p2",
    "p3",
    "mp3",
    "alltid_nyheter",
    "klassisk",
    "jazz",
    "radio_super",
]
DEFAULT_SHOWS = ["podcast/dagsnytt_atten", "series/nyhetsmorgen"]

# Media identifiers (the part after media-source://nrk_radio/):
#   channel/<id>                      live channel
#   podcast/<id>, series/<id>         a show; playing it starts its first episode
#   episode/<podcast|series>/<show>/<id>
#   program/<id>                      standalone programme
#   page/<id>, section/<page>/<n>     category pages, browse only
KIND_CHANNEL = "channel"
KIND_PODCAST = "podcast"
KIND_SERIES = "series"
KIND_EPISODE = "episode"
KIND_PROGRAM = "program"
KIND_PAGE = "page"
KIND_SECTION = "section"

CARD_URL = "/nrk_radio/nrk-radio-card.js"
