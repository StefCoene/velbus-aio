"""Test that name memory in the module specs is internally consistent.

A channel name, a module name and a channel-enable flag each own a fixed
piece of eeprom. If two of those claim the same address, reading a name
returns unrelated bytes and -- worse -- writing one silently destroys the
other. These tests walk every spec and assert that never happens.
"""

import json
import pathlib

import pytest

SPEC_DIR = pathlib.Path(__file__).parent.parent / "velbusaio" / "module_spec"

# A Velbus name is 16 characters. A few older modules reserve only 15.
NAME_WIDTHS = (15, 16)


def _specs():
    """Yield (module id, parsed spec) for every module spec."""
    for path in sorted(SPEC_DIR.glob("*.json")):
        yield path.stem, json.loads(path.read_text())


def _ranges(value):
    """Parse "0000-000F" or "00EA-00EF;01EA-01EF" into [(start, end), ...]."""
    out = []
    for part in value.split(";"):
        start, _, end = part.partition("-")
        out.append((int(start, 16), int(end, 16)))
    return out


def _claims(memory):
    """Return [(label, start, end), ...] for everything that owns name memory."""
    claims = []
    for chan, value in (memory.get("Channels") or {}).items():
        if isinstance(value, str):
            for start, end in _ranges(value):
                claims.append((f"name of channel {chan}", start, end))
    module_name = memory.get("ModuleName")
    if isinstance(module_name, str):
        for start, end in _ranges(module_name):
            claims.append(("module name", start, end))
    enable = (memory.get("ChannelEnable") or {}).get("channels") or {}
    for chan, value in enable.items():
        if isinstance(value, str):
            addr = int(value, 16)
            claims.append((f"enable flag of channel {chan}", addr, addr))
    return claims


SPECS = list(_specs())


@pytest.mark.parametrize("module,spec", SPECS, ids=[m for m, _ in SPECS])
def test_name_memory_does_not_overlap(module, spec):
    """No two name-memory claims in a spec may cover the same address."""
    memory = spec.get("Memory")
    if not isinstance(memory, dict):
        pytest.skip(f"{module} declares no memory")
    claims = _claims(memory)
    if len(claims) < 2:
        pytest.skip(f"{module} declares less than two name-memory ranges")

    for i, (label_a, start_a, end_a) in enumerate(claims):
        for label_b, start_b, end_b in claims[i + 1 :]:
            assert not (start_a <= end_b and start_b <= end_a), (
                f"{spec.get('Type', module)}: {label_a} "
                f"(0x{start_a:04X}-0x{end_a:04X}) overlaps {label_b} "
                f"(0x{start_b:04X}-0x{end_b:04X})"
            )


@pytest.mark.parametrize("module,spec", SPECS, ids=[m for m, _ in SPECS])
def test_channel_name_width(module, spec):
    """A channel name reserves 15 or 16 bytes, even when split over banks."""
    channels = (spec.get("Memory") or {}).get("Channels") or {}
    if not channels:
        pytest.skip(f"{module} declares no channel names")

    for chan, value in channels.items():
        if not isinstance(value, str):
            continue
        width = sum(end - start + 1 for start, end in _ranges(value))
        assert width in NAME_WIDTHS, (
            f"{spec.get('Type', module)}: name of channel {chan} ({value}) "
            f"reserves {width} bytes, expected one of {NAME_WIDTHS}"
        )
