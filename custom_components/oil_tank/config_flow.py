"""Config flow for the Heating Oil Tank integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_CAPACITY,
    CONF_FLOW_RATE,
    CONF_INITIAL_CM,
    CONF_LITERS_PER_CM,
    CONF_LOW_ALERT,
    CONF_PRICE_ENTITY,
    CONF_RUNTIME_ENTITY,
    DEFAULT_CAPACITY,
    DEFAULT_FLOW_RATE,
    DEFAULT_LITERS_PER_CM,
    DEFAULT_LOW_ALERT,
    DEFAULT_NAME,
    DOMAIN,
    MAX_FLOW_RATE,
    MIN_FLOW_RATE,
)


def _num(min_v: float, max_v: float, step: float, unit: str) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=min_v, max=max_v, step=step, unit_of_measurement=unit, mode=NumberSelectorMode.BOX
        )
    )


SENSOR = EntitySelector(EntitySelectorConfig(domain="sensor"))

TANK_FIELDS = {
    vol.Required(CONF_CAPACITY, default=DEFAULT_CAPACITY): _num(50, 100000, 1, "L"),
    vol.Required(CONF_LITERS_PER_CM, default=DEFAULT_LITERS_PER_CM): _num(0.1, 1000, 0.1, "L/cm"),
    vol.Required(CONF_LOW_ALERT, default=DEFAULT_LOW_ALERT): _num(0, 100000, 10, "L"),
}


class OilTankConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up an oil tank."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_RUNTIME_ENTITY])
            self._abort_if_unique_id_configured()
            if user_input[CONF_INITIAL_CM] * user_input[CONF_LITERS_PER_CM] > user_input[CONF_CAPACITY]:
                errors[CONF_INITIAL_CM] = "above_capacity"
            else:
                return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(CONF_RUNTIME_ENTITY): SENSOR,
                vol.Optional(CONF_PRICE_ENTITY): SENSOR,
                **TANK_FIELDS,
                vol.Required(CONF_FLOW_RATE, default=DEFAULT_FLOW_RATE): _num(
                    MIN_FLOW_RATE, MAX_FLOW_RATE, 0.01, "L/h"
                ),
                vol.Required(CONF_INITIAL_CM, default=0): _num(0, 1000, 0.5, "cm"),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OilTankOptionsFlow:
        return OilTankOptionsFlow()


class OilTankOptionsFlow(OptionsFlow):
    """Change tank settings. Level and flow rate are changed with actions."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            user_input.setdefault(CONF_PRICE_ENTITY, None)
            return self.async_create_entry(data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Required(CONF_RUNTIME_ENTITY): SENSOR,
                vol.Optional(CONF_PRICE_ENTITY): SENSOR,
                **TANK_FIELDS,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema, {k: v for k, v in current.items() if v is not None}
            ),
        )
