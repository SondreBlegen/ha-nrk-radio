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

## The card

Loaded automatically by the integration; no resource to add.

```yaml
type: custom:nrk-radio-card
show: series/doedens-budbaerer     # lock to one series or podcast
speaker: media_player.kitchen  # optional: always play here (else a dropdown)
```

Leave out `show` and the card becomes a library browser with search.
Episode rows show **▶** when nothing is playing and **add to queue** when
something is. Queued rows show their place and an **×** to remove them.

`show` takes the id from a radio.nrk.no link: `radio.nrk.no/serie/nyhetsmorgen`
is `series/nyhetsmorgen`, and `radio.nrk.no/podkast/dagsnytt_atten` is
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
