"""Build the device -> entity tree shown in the panel."""
from __future__ import annotations

from typing import Any

NO_DEVICE = "__no_device__"


def build_tree(
    devices: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    excluded: set[str],
    counts: dict[str, int],
) -> list[dict[str, Any]]:
    """devices: {id,name}; entities: {entity_id,name,device_id,platform,domain}."""
    dev_names = {d["id"]: d.get("name") or "Unnamed device" for d in devices}
    groups: dict[str, list[dict[str, Any]]] = {}
    for ent in entities:
        eid = ent["entity_id"]
        item = {
            "entity_id": eid,
            "name": ent.get("name") or eid,
            "domain": ent.get("domain") or eid.split(".", 1)[0],
            "platform": ent.get("platform") or "",
            "recorded": eid not in excluded,
            "records": counts.get(eid, 0),
        }
        groups.setdefault(ent.get("device_id") or NO_DEVICE, []).append(item)

    tree = []
    for dev_id, items in groups.items():
        items.sort(key=lambda i: i["entity_id"])
        tree.append(
            {
                "device_id": dev_id,
                "name": "Entities without device" if dev_id == NO_DEVICE else dev_names.get(dev_id, "Unknown device"),
                "entities": items,
                "records": sum(i["records"] for i in items),
                "excluded_count": sum(1 for i in items if not i["recorded"]),
            }
        )
    tree.sort(key=lambda d: (d["device_id"] == NO_DEVICE, d["name"].lower()))
    return tree
