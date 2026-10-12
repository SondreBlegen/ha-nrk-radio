"""Config flow: pick speakers, favourite channels and favourite shows."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.components.media_player import DOMAIN as MP_DOMAIN
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
)

from .api import NrkApi, NrkError
from .const import (
    CONF_CHANNELS,
    CONF_SHOWS,
    CONF_SPEAKERS,
    DEFAULT_CHANNELS,
    DEFAULT_SHOWS,
    DOMAIN,
    KIND_PODCAST,
    KIND_SERIES,
)

# radio.nrk.no/podkast/<id>/..., radio.nrk.no/serie/<id>/...
_LINK = re.compile(r"/(podkast|serie)/([^/?#]+)")


def _cast_speakers(hass: HomeAssistant) -> list[str]:
    registry = er.async_get(hass)
    return sorted(
        e.entity_id
        for e in registry.entities.values()
        if e.domain == MP_DOMAIN and e.platform == "cast" and not e.disabled
    )


async def _show_ref(api: NrkApi, value: str) -> str:
    """'series/x', a radio.nrk.no link, or a bare id -> 'podcast/x' / 'series/x'."""
    value = value.strip()
    if match := _LINK.search(value):
        kind = KIND_PODCAST if match[1] == "podkast" else KIND_SERIES
        await api.show(kind, match[2])
        return f"{kind}/{match[2]}"
    kind, _, show_id = value.partition("/")
    if kind in (KIND_PODCAST, KIND_SERIES) and show_id:
        await api.show(kind, show_id)
        return value
    show = await api.find_show(value)
    return f"{show.kind}/{show.id}"


async def _async_form(
    hass: HomeAssistant, user_input: dict[str, Any] | None, current: dict[str, Any]
) -> tuple[dict[str, Any] | None, vol.Schema, dict[str, str]]:
    """Validate input if given; return (options or None, schema, errors)."""
    api = NrkApi(async_get_clientsession(hass))
    errors: dict[str, str] = {}
    try:
        channels = await api.channels()
    except NrkError:
        channels = []
        errors["base"] = "cannot_connect"

    if user_input is not None and not errors:
        shows: list[str] = []
        for value in user_input.get(CONF_SHOWS, []):
            if not value.strip():
                continue
            try:
                shows.append(await _show_ref(api, value))
            except NrkError:
                errors[CONF_SHOWS] = "unknown_show"
                break
        if not user_input.get(CONF_SPEAKERS):
            errors[CONF_SPEAKERS] = "no_speakers"
        if not errors:
            return {**user_input, CONF_SHOWS: shows}, vol.Schema({}), errors
        current = user_input

    schema = vol.Schema(
        {
            vol.Required(
                CONF_SPEAKERS, default=current.get(CONF_SPEAKERS, _cast_speakers(hass))
            ): EntitySelector(EntitySelectorConfig(domain=MP_DOMAIN, multiple=True)),
            vol.Optional(
                CONF_SHOWS, default=current.get(CONF_SHOWS, DEFAULT_SHOWS)
            ): TextSelector(TextSelectorConfig(multiple=True)),
            vol.Optional(
                CONF_CHANNELS, default=current.get(CONF_CHANNELS, DEFAULT_CHANNELS)
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[SelectOptionDict(value=c.id, label=c.title) for c in channels],
                    multiple=True,
                )
            ),
        }
    )
    return None, schema, errors


class NrkRadioConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        options, schema, errors = await _async_form(self.hass, user_input, {})
        if options is not None:
            return self.async_create_entry(title="NRK Radio", data={}, options=options)
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return NrkRadioOptionsFlow()


class NrkRadioOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        options, schema, errors = await _async_form(
            self.hass, user_input, dict(self.config_entry.options)
        )
        if options is not None:
            return self.async_create_entry(data=options)
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
