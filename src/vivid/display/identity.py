"""Stable display identity matching.

Connector names (``DP-1``, ``HDMI-A-1``) can change when the topology changes.
Vivid prefers KWin's EDID hash, then the output UUID, and uses the connector
only as a last resort.  When two connected outputs share an EDID hash and no
disambiguating identity exists, the identity is marked ambiguous and automatic
restoration is disabled until the user acts explicitly.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable

from ..models import DisplayIdentity, DisplayInfo


def _clean(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return cleaned[:96]


def stable_id_for(
    edid_hash: str = "",
    uuid: str = "",
    connector: str = "",
    unique_edid: bool = True,
) -> tuple[str, str, bool]:
    if edid_hash and unique_edid:
        return f"edid-{_clean(edid_hash)}", "edid", False
    if uuid:
        return f"uuid-{_clean(uuid)}", "uuid", not unique_edid
    if edid_hash:
        return f"edid-{_clean(edid_hash)}-{_clean(connector)}", "edid+connector", True
    if connector:
        return f"connector-{_clean(connector)}", "connector", True
    return "unknown", "unknown", True


def assign_identities(displays: Iterable[DisplayInfo]) -> list[DisplayInfo]:
    items = list(displays)
    groups: dict[str, list[DisplayInfo]] = defaultdict(list)
    for display in items:
        if display.edid_hash:
            groups[display.edid_hash].append(display)
    for display in items:
        count = groups.get(display.edid_hash, []) if display.edid_hash else []
        unique = len(count) <= 1
        stable_id, source, ambiguous = stable_id_for(
            edid_hash=display.edid_hash,
            uuid=display.uuid,
            connector=display.output_name,
            unique_edid=unique,
        )
        display.identity = DisplayIdentity(
            stable_id=stable_id,
            source=source,
            ambiguous=ambiguous,
            edid_hash=display.edid_hash,
            edid_identifier=display.edid_identifier,
            manufacturer=display.manufacturer,
            model=display.model,
            serial=display.serial,
            uuid=display.uuid,
        )
    return items
