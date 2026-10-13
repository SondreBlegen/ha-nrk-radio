"""NRK Radio: NRK's live channels and on-demand library, cast to your speakers."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from . import ma
from .api import NrkApi
from .const import CARD_URL, CONF_CHANNELS, CONF_SHOWS, CONF_SPEAKERS, DOMAIN
from .controller import RadioController

PLATFORMS = [Platform.MEDIA_PLAYER, Platform.SELECT, Platform.SWITCH, Platform.BUTTON]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type NrkConfigEntry = ConfigEntry[RadioController]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the episode card and load it on every dashboard."""
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(Path(__file__).parent / "nrk-radio-card.js"), False)]
    )
    # The version busts browser caches when the card changes.
    url = f"{CARD_URL}?v={integration.version}"
    if not await _async_register_resource(hass, url):
        add_extra_js_url(hass, url)
    ma.async_register(hass)
    return True


async def _async_register_resource(hass: HomeAssistant, url: str) -> bool:
    """Load the card as a dashboard resource, as HACS cards are.

    Dashboards fetch their resources on every load, whereas extra scripts are
    baked into the start page that the companion apps keep for days. Returns
    False when resources are YAML-managed and can't be written.
    """
    resources = getattr(hass.data.get(LOVELACE_DATA), "resources", None)
    if resources is None or not hasattr(resources, "async_create_item"):
        return False
    await resources.async_get_info()  # loads the collection from storage
    for item in resources.async_items():
        if item["url"].split("?", 1)[0] == CARD_URL:
            if item["url"] != url:
                await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
            return True
    await resources.async_create_item({"res_type": "module", "url": url})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NrkConfigEntry) -> bool:
    options = entry.options
    controller = RadioController(
        hass,
        NrkApi(async_get_clientsession(hass)),
        speakers=list(options.get(CONF_SPEAKERS, [])),
        favourite_channels=list(options.get(CONF_CHANNELS, [])),
        favourite_shows=list(options.get(CONF_SHOWS, [])),
    )
    await controller.async_start()
    entry.runtime_data = controller
    entry.async_on_unload(controller.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NrkConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: NrkConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
