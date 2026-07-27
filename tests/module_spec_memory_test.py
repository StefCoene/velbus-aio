"""Test cases for the memory maps declared in module_spec/*.json"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

SPEC_DIR = Path(__file__).parent.parent / "velbusaio" / "module_spec"
SPECS = sorted(SPEC_DIR.glob("*.json"))


def parse_ranges(value: str | None) -> list[tuple[int, int]]:
    """Parse 'AAAA-BBBB;CCCC-DDDD' into inclusive integer ranges."""
    out: list[tuple[int, int]] = []
    for part in (value or "").split(";"):
        part = part.strip()
        if "-" not in part:
            continue
        lo, hi = part.split("-", 1)
        out.append((int(lo, 16), int(hi, 16)))
    return out


def declared_regions(spec: dict) -> list[tuple[int, int, str]]:
    """Return every (start, end, label) region a spec lays claim to in EEPROM."""
    memory = spec.get("Memory") or {}
    regions: list[tuple[int, int, str]] = []

    for low, high in parse_ranges(memory.get("ModuleName")):
        regions.append((low, high, "ModuleName"))

    for channel, value in (memory.get("Channels") or {}).items():
        if isinstance(value, str):
            for low, high in parse_ranges(value):
                regions.append((low, high, f"ChannelName[{channel}]"))

    table = memory.get("ActionTable")
    if table:
        span = table["slot_count"] * table["slot_size"]
        # Two shapes exist: one table shared by every channel (bank on the table
        # itself), or one table per channel (bank on each channel entry).
        shared_bank = table.get("bank")
        if shared_bank is not None:
            base = int(str(shared_bank), 16)
            regions.append((base, base + span - 1, "ActionTable"))
        for channel, config in (table.get("channels") or {}).items():
            if not isinstance(config, dict):
                continue
            bank = config.get("bank")
            if bank is not None:
                base = int(str(bank), 16)
                regions.append((base, base + span - 1, f"ActionTable[{channel}]"))
            noc = config.get("noc_address")
            if noc is not None:
                addr = int(str(noc), 16)
                regions.append((addr, addr, f"NOC[{channel}]"))

    return regions


@pytest.mark.parametrize("path", SPECS, ids=lambda p: p.name)
def test_memory_regions_do_not_overlap(path: Path) -> None:
    """Two claims on one EEPROM address means one of them is wrong.

    The action table, the NO/NC contact byte, the channel names and the module
    name each occupy their own area of module memory. An overlap is not
    cosmetic: reading returns bytes belonging to something else, and writing
    corrupts it. VMB4RYLD, VMB4RYNO, VMB1RYNO, VMBDMI and VMBDMI-R all carried
    an action table sized for a firmware build that predates the module name,
    so the last slots -- and for the relays the NO/NC byte -- landed inside the
    name.
    """
    spec = json.loads(path.read_text())
    regions = declared_regions(spec)

    overlaps = [
        f"{label_a} 0x{low_a:04X}-0x{high_a:04X} overlaps "
        f"{label_b} 0x{low_b:04X}-0x{high_b:04X}"
        for index, (low_a, high_a, label_a) in enumerate(regions)
        for low_b, high_b, label_b in regions[index + 1 :]
        if low_a <= high_b and low_b <= high_a
    ]

    assert not overlaps, f"{path.name} ({spec.get('Type')}): " + "; ".join(overlaps)


@pytest.mark.parametrize("path", SPECS, ids=lambda p: p.name)
def test_action_table_is_fully_specified(path: Path) -> None:
    """An action table without slot_count/slot_size/bank cannot be addressed."""
    spec = json.loads(path.read_text())
    table = (spec.get("Memory") or {}).get("ActionTable")
    if table is None:
        pytest.skip("no action table")

    assert table["slot_count"] > 0
    assert table["slot_size"] > 0
    assert table["channels"], "an action table needs at least one channel"

    shared_bank = table.get("bank")
    for channel, config in table["channels"].items():
        assert isinstance(config, dict), f"channel {channel} is not a mapping"
        bank = config.get("bank", shared_bank)
        assert bank is not None, f"channel {channel} has no bank and none is shared"
        int(str(bank), 16)
