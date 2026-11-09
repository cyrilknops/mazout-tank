"""Heating Oil Tank: tank level from the burner runtime counter."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_GAUGE_CM,
    ATTR_LITERS,
    CARD_URL,
    DOMAIN,
    SERVICE_ADD_DELIVERY,
    SERVICE_CALIBRATE_FLOW,
    SERVICE_SET_LEVEL,
    VERSION,
)
from .tank import OilTank

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.NUMBER]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type OilTankConfigEntry = ConfigEntry[OilTank]

_BASE = {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}
DELIVERY_SCHEMA = vol.Schema({**_BASE, vol.Required(ATTR_LITERS): vol.Coerce(float)})
LEVEL_SCHEMA = vol.All(
    vol.Schema(
        {
            **_BASE,
            vol.Optional(ATTR_LITERS): vol.Coerce(float),
            vol.Optional(ATTR_GAUGE_CM): vol.Coerce(float),
        }
    ),
    cv.has_at_least_one_key(ATTR_LITERS, ATTR_GAUGE_CM),
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the card and the actions."""
    card_path = Path(__file__).parent / "www" / "oil-tank-card.js"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(card_path), False)]
    )
    # A hash of the file in the URL: proxies and browsers that cache the
    # card always get the new file after an update.
    card_hash = await hass.async_add_executor_job(
        lambda: hashlib.sha1(card_path.read_bytes()).hexdigest()[:10]
    )
    await _async_register_card(hass, f"{CARD_URL}?v={VERSION}-{card_hash}")

    def _tank(call: ServiceCall) -> OilTank:
        entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
        entries = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.state is ConfigEntryState.LOADED
            and (entry_id is None or e.entry_id == entry_id)
        ]
        if len(entries) != 1:
            raise ServiceValidationError(
                "Select the oil tank (config_entry_id)."
                if entries
                else "No loaded oil tank found."
            )
        return entries[0].runtime_data

    def _liters(tank: OilTank, call: ServiceCall) -> float:
        if ATTR_LITERS in call.data:
            return float(call.data[ATTR_LITERS])
        return float(call.data[ATTR_GAUGE_CM]) * tank.liters_per_cm

    async def add_delivery(call: ServiceCall) -> None:
        _tank(call).add_delivery(call.data[ATTR_LITERS])

    async def set_level(call: ServiceCall) -> None:
        tank = _tank(call)
        tank.set_level(_liters(tank, call))

    async def calibrate_flow(call: ServiceCall) -> ServiceResponse:
        tank = _tank(call)
        result = tank.calibrate_flow(_liters(tank, call))
        persistent_notification.async_create(
            hass,
            result["message"],
            title=f"{tank.entry.title}: calibration",
            notification_id=f"{DOMAIN}_{tank.entry.entry_id}_calibration",
        )
        return result

    hass.services.async_register(DOMAIN, SERVICE_ADD_DELIVERY, add_delivery, DELIVERY_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SET_LEVEL, set_level, LEVEL_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_CALIBRATE_FLOW,
        calibrate_flow,
        LEVEL_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def _async_register_card(hass: HomeAssistant, url: str) -> None:
    """Load the card on every dashboard.

    Dashboards in storage mode get a dashboard resource. Resources come
    through the live connection, so a cached start page (service worker,
    reverse proxy, kiosk browser) cannot hide a new card version.
    YAML-mode dashboards fall back to an extra frontend module.
    """
    ll_data = hass.data.get(LOVELACE_DATA)
    if ll_data is None or ll_data.resource_mode != "storage":
        _LOGGER.info("Dashboards use YAML resources; add %s as a module resource", url)
        add_extra_js_url(hass, url)
        return

    resources = ll_data.resources
    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True

    mine = [r for r in resources.async_items() if r.get("url", "").split("?")[0] == CARD_URL]
    if not mine:
        await resources.async_create_item({"res_type": "module", "url": url})
        return
    if mine[0].get("url") != url or mine[0].get("type") != "module":
        await resources.async_update_item(mine[0]["id"], {"res_type": "module", "url": url})
    for duplicate in mine[1:]:
        await resources.async_delete_item(duplicate["id"])


async def async_setup_entry(hass: HomeAssistant, entry: OilTankConfigEntry) -> bool:
    tank = OilTank(hass, entry)
    await tank.async_load()
    entry.runtime_data = tank
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OilTankConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_unload()
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: OilTankConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
