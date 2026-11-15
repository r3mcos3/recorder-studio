from __future__ import annotations

import copy

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DEFAULT_DATA, DOMAIN, STORAGE_KEY, STORAGE_VERSION


def _merge(loaded: dict | None) -> dict:
    data = copy.deepcopy(DEFAULT_DATA)
    if loaded:
        opts = {**data["options"], **loaded.get("options", {})}
        alerts = {**data["alerts"], **(loaded.get("alerts") or {})}
        data.update({k: v for k, v in loaded.items() if k in data})
        data["options"] = opts
        data["alerts"] = alerts
    data["dismissed"] = sorted({str(e).strip() for e in data["dismissed"] if str(e).strip()})
    for key in ("excluded_entities", "rescued_entities"):
        data[key] = sorted({str(e).strip() for e in data[key] if str(e).strip()})
    return data


async def async_load(hass: HomeAssistant) -> dict:
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    data = _merge(await store.async_load())
    hass.data.setdefault(DOMAIN, {}).update(store=store, data=data)
    return data


async def async_save(hass: HomeAssistant) -> None:
    domain = hass.data[DOMAIN]
    domain["data"] = _merge(domain["data"])
    await domain["store"].async_save(domain["data"])
