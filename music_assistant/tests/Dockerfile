# The NRK provider inside the Music Assistant release running at home.
#   docker build -t nrk-ma-test -f music_assistant/tests/Dockerfile .
#   docker run --rm nrk-ma-test
FROM ghcr.io/music-assistant/server:2.10.6
COPY music_assistant/nrk_radio /app/venv/lib/python3.14/site-packages/music_assistant/providers/nrk_radio
COPY music_assistant/tests/live_check.py /tmp/live_check.py
ENTRYPOINT ["python", "/tmp/live_check.py"]
