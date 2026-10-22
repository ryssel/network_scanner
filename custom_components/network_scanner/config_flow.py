import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)
from .const import DOMAIN
import logging

_LOGGER = logging.getLogger(__name__)

class NetworkScannerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Network Scanner."""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return NetworkScannerOptionsFlow()

    async def async_step_user(self, user_input=None):
        def format_dict_for_printing(d):
            return {k: str(v) for k, v in d.items()}

        """Manage the configurations from the user interface."""
        errors = {}

        # Load data from configuration.yaml. Namespaced under "_yaml_config"
        # since hass.data[DOMAIN] also holds per-entry coordinators keyed by
        # entry_id (see __init__.py's async_setup_entry).
        yaml_config = self.hass.data.get(DOMAIN, {}).get("_yaml_config", {})
        _LOGGER.debug("YAML Config: %s", yaml_config)

        if user_input is not None:
            return self.async_create_entry(title="Network Scanner", data=user_input)

        data_schema_dict = {
            vol.Required("ip_range", description={"suggested_value": yaml_config.get("ip_range", "192.168.1.0/24")}): str
        }

        # Add mac mappings with values from YAML if available
        for i in range(1, 26):  # Ensure at least 25 entries
            key = f"mac_mapping_{i}"
            if key in yaml_config:
                suggested_value = yaml_config.get(key)
                _LOGGER.debug("YAML Config key: %s", suggested_value)
            else:
                suggested_value = None  # No value in YAML config
            
            # Add the optional field to the schema, with or without suggested_value
            data_schema_dict[vol.Optional(key, description={"suggested_value": suggested_value})] = str

        # Continue to add more mappings if available in the YAML config
        i = 26
        while True:
            key = f"mac_mapping_{i}"
            if key in yaml_config:
                suggested_value = yaml_config.get(key)
                _LOGGER.debug("YAML Config key: %s", suggested_value)
                data_schema_dict[vol.Optional(key, description={"suggested_value": suggested_value})] = str
                i += 1
            else:
                break  # Exit loop when no more mappings are found in the YAML config

        _LOGGER.debug("schema: %s", format_dict_for_printing(data_schema_dict))
        data_schema = vol.Schema(data_schema_dict)

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={"description": "Enter the IP range and MAC mappings"}
        )


def _mac_mapping_keys(data):
    """mac_mapping_N keys in data, sorted by N."""
    keys = [k for k in data if k.startswith("mac_mapping_") and k[12:].isdigit()]
    return sorted(keys, key=lambda k: int(k[12:]))


def _current_mapping_text(data):
    return "\n".join(data[k] for k in _mac_mapping_keys(data) if data[k])


class NetworkScannerOptionsFlow(config_entries.OptionsFlow):
    """Edit the MAC mappings of an existing entry (the Configure button).

    The mappings are edited as one text block, one MAC;Name;Description per
    line, and written back to entry.data as mac_mapping_1..N - the format
    async_setup_entry already reads. Writing data (not options) keeps a
    removed line from surviving in the old data. The update listener in
    __init__.py reloads the entry.
    """

    def __init__(self):
        self._prefill = None

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=["add", "edit"])

    async def async_step_add(self, user_input=None):
        """Pick devices from the last scan that have no mapping yet."""
        entry = self.config_entry

        if user_input is not None:
            picked = set(user_input.get("devices", []))
            new_lines = [line for mac, line in self._candidates if mac in picked]
            self._prefill = "\n".join(
                [_current_mapping_text(entry.data), *new_lines]
            ).strip()
            return await self.async_step_edit()

        mapped = {
            entry.data[k].split(";", 1)[0].strip().lower()
            for k in _mac_mapping_keys(entry.data)
            if entry.data[k]
        }
        coordinator = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
        scanned = (coordinator.data if coordinator else None) or []

        self._candidates = []
        options = []
        seen = set()
        for dev in scanned:
            mac = dev["mac"].lower()
            if mac in mapped or mac in seen:
                continue
            seen.add(mac)
            hostname = dev.get("hostname") or ""
            vendor = dev.get("vendor") or ""
            name = (hostname or vendor or "Unknown").replace(";", ",")
            desc = vendor.replace(";", ",")
            self._candidates.append((mac, f"{dev['mac']};{name};{desc}"))
            label = f"{dev['ip']}  {dev['mac']}  {hostname or '(no hostname)'}  ({vendor})"
            options.append(SelectOptionDict(value=mac, label=label))

        if not options:
            return self.async_abort(reason="no_new_devices")

        return self.async_show_form(
            step_id="add",
            data_schema=vol.Schema(
                {
                    vol.Optional("devices", default=[]): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_edit(self, user_input=None):
        errors = {}
        entry = self.config_entry

        if user_input is not None:
            lines = [
                line.strip()
                for line in user_input.get("mac_mappings", "").splitlines()
                if line.strip()
            ]
            bad = [line for line in lines if line.count(";") < 2]
            if bad:
                errors["mac_mappings"] = "invalid_mapping"
            else:
                data = {"ip_range": entry.data.get("ip_range")}
                for i, line in enumerate(lines, start=1):
                    data[f"mac_mapping_{i}"] = line
                self.hass.config_entries.async_update_entry(entry, data=data)
                return self.async_create_entry(data={})
            current = user_input.get("mac_mappings", "")
        elif self._prefill is not None:
            current = self._prefill
        else:
            current = _current_mapping_text(entry.data)

        return self.async_show_form(
            step_id="edit",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "mac_mappings", description={"suggested_value": current}
                    ): TextSelector(TextSelectorConfig(multiline=True)),
                }
            ),
            errors=errors,
        )
