# NRK Radio for Home Assistant

NRK's on-demand library (radio series, radio dramas, podcasts, documentaries)
and its live channels, played on your Cast speakers with a real queue.

## What you get

| Entity | What it does |
|---|---|
| `media_player.nrk_radio` | Remote for the chosen speaker. Browse/search the library, play, queue, next/previous. |
| `select.nrk_radio_speaker` | Which speaker plays. Changing it mid-episode moves playback, position and all. |
| `switch.nrk_radio_keep_playing` | Off: stop when the queue is done. On: carry on with the show's next episode. |
| `button.nrk_radio_*` | One tap per favourite channel or show. |

Plus the NRK library in HA's **Media** panel for any speaker, and Assist:
*"play Dagsnytt 18 on NRK Radio"* works through `media_player.search_media`.

### Queue rules

- **Play** replaces the queue. **Add to queue** (card, media browser, or
  `enqueue: add`) appends without interrupting.
- When an episode ends, the next queued one starts. When the queue runs out,
  playback stops, unless *keep playing* is on.
- Next/previous step through the queue, then on through the show.
  Radio dramas and serials go in story order (episode 1, 2, 3...); news and
  podcasts go newest first.
- Live radio never ends, so it always replaces the queue; next/previous then
  flip between your favourite channels.

## Music Assistant

From v0.4 the card plays through [Music Assistant](https://music-assistant.io):
Music Assistant owns the players, the queue and keep-playing (its *Autoplay*), and
the card works on anything Music Assistant can play: NRK, Spotify, YouTube Music...

NRK reaches Music Assistant through the provider in `music_assistant/nrk_radio`.
Music Assistant has no way to install outside providers yet, so it is copied into
the add-on container and the add-on restarted (on HAOS the container is named
`addon_…` or `app_…` depending on the Supervisor version; `docker ps` shows it):

```bash
docker cp music_assistant/nrk_radio app_d5369777_music_assistant:/app/venv/lib/python3.14/site-packages/music_assistant/providers/
docker restart app_d5369777_music_assistant
```

Then add **NRK Radio** under Music Assistant → Settings → Providers. A Music Assistant
update replaces the container, so repeat the copy after updating until the provider
is part of Music Assistant itself.

Autoplay continues a show with its next episode: part 2 after part 1 for radio
dramas, the next *newer* episode for news and podcasts.

## The card

Loaded automatically by the integration; no resource to add.

```yaml
type: custom:nrk-radio-card
show: podcast/fantorangens_vitseshow   # an NRK show (series/<id> for radio series)
player: media_player.kitchen_display   # a Music Assistant player (else a dropdown)
episodes: 5                            # rows shown before "Show all"
```

`uri:` takes any Music Assistant item instead of `show:`, for example
`spotify://playlist/<id>`. Leave both out and the card becomes a browser: search,
plus every Music Assistant provider.

Rows show **▶** when nothing is playing and **add to queue** when something is.
Queued rows show their place and an **×** to remove them. Queued episodes play
in turn; when the queue is done, playback stops unless *keep playing* is on.

`show` takes the id from a radio.nrk.no link: `radio.nrk.no/serie/doedens-budbaerer`
is `series/doedens-budbaerer`, and `radio.nrk.no/podkast/dagsnytt_atten` is
`podcast/dagsnytt_atten`.

## Scripts and automations

```yaml
action: media_player.play_media
target: { entity_id: media_player.nrk_radio }
data:
  media_content_type: music
  media_content_id: series/nyhetsmorgen        # or channel/p1, podcast/..., episode/series/<show>/<id>
  enqueue: add                                  # optional
  extra: { speaker: media_player.kitchen }  # optional
```

## How it works

Everything comes from `psapi.nrk.no`, the open API radio.nrk.no itself uses.
No login is needed. Podcasts are MP3. Live channels and the radio archive are
audio-only HLS (MPEG-TS), sent to Cast with `hlsSegmentFormat: ts`.

## Development

```bash
docker build -t nrk-radio-test tests
docker build -t nrk-radio-run -f - . <<'EOF'
FROM nrk-radio-test
COPY . /repo
WORKDIR /repo
EOF
docker run --rm nrk-radio-run
```

`tests/card/harness.html` renders the card against captured NRK data
(`tests/card/capture.py`) with a simulated `hass`. Serve the repo over HTTP
and open it.
