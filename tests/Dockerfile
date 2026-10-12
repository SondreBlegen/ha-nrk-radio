# Test image pinned to the Home Assistant version running at home.
#   docker build -t nrk-radio-test tests
#   docker run --rm -v "$PWD:/repo" -w /repo nrk-radio-test
FROM python:3.14-slim
RUN pip install --no-cache-dir "homeassistant==2026.9.3" pytest-homeassistant-custom-component
# The card is served through the frontend component, which needs its package.
RUN pip install --no-cache-dir -c /usr/local/lib/python3.14/site-packages/homeassistant/package_constraints.txt home-assistant-frontend
CMD ["python", "-m", "pytest", "-q", "tests"]
