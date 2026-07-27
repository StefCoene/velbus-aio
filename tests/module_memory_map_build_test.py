"""Test the memory map build check on Module."""

import glob
import json
import logging
import os
import pathlib
import re

import pytest

from velbusaio.exceptions import VelbusMemoryWriteBlocked
from velbusaio.module import Module

SPEC_DIR = pathlib.Path(__file__).parent.parent / "velbusaio" / "module_spec"

# 0x10 VMB4RYLD declares MemoryMapBuild 1409, 0x12 VMB4DC declares 1915 and
# 0x13 VMBLCDWB declares none.
VMB4RYLD = 0x10
VMB4DC = 0x12
VMBLCDWB = 0x13


class MockWriter:
    async def __call__(self, data):
        pass


class MockController:
    """Mock controller for testing."""

    def connected(self):
        return True

    def _add_on_connext_callback(self, callback):
        pass

    def _remove_on_connect_callback(self, callback):
        pass

    def _add_on_disconnect_callback(self, callback):
        pass

    def _remove_on_disconnect_callback(self, callback):
        pass


async def _build(module_type, year, week):
    module = Module(1, module_type, build_year=year, build_week=week)
    module._use_cache = False
    await module.initialize(MockWriter(), MockController())
    return module


def _mismatch_warnings(caplog):
    return [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "memory map from build" in r.message
    ]


@pytest.mark.asyncio
async def test_older_build_warns(caplog):
    """A module predating the spec's memory map is reported."""
    with caplog.at_level(logging.WARNING, logger="velbus-module"):
        await _build(VMB4DC, year=18, week=2)

    warnings = _mismatch_warnings(caplog)
    assert len(warnings) == 1
    assert "reports build 1802" in warnings[0].message
    assert "from build 1915 onwards" in warnings[0].message


@pytest.mark.asyncio
async def test_exact_build_is_quiet(caplog):
    """The first build the map applies to is a match, not a mismatch."""
    with caplog.at_level(logging.WARNING, logger="velbus-module"):
        await _build(VMB4RYLD, year=14, week=9)

    assert _mismatch_warnings(caplog) == []


@pytest.mark.asyncio
async def test_one_week_older_warns(caplog):
    """Week 8 of year 14 is 1408, which is below 1409.

    This only holds if the week is zero padded; an unpadded "148" would
    compare as greater than "1409" and the mismatch would go unnoticed.
    """
    with caplog.at_level(logging.WARNING, logger="velbus-module"):
        await _build(VMB4RYLD, year=14, week=8)

    warnings = _mismatch_warnings(caplog)
    assert len(warnings) == 1
    assert "reports build 1408" in warnings[0].message


@pytest.mark.asyncio
async def test_newer_build_is_quiet(caplog):
    """Firmware newer than the documented map is the normal case."""
    with caplog.at_level(logging.WARNING, logger="velbus-module"):
        await _build(VMB4DC, year=25, week=1)

    assert _mismatch_warnings(caplog) == []


@pytest.mark.asyncio
async def test_spec_without_build_is_quiet(caplog):
    """Most specs declare no build; those must never warn."""
    with caplog.at_level(logging.WARNING, logger="velbus-module"):
        await _build(VMBLCDWB, year=10, week=1)

    assert _mismatch_warnings(caplog) == []


@pytest.mark.asyncio
async def test_module_without_build_is_quiet(caplog):
    """A module restored from a cache may not carry build information."""
    with caplog.at_level(logging.WARNING, logger="velbus-module"):
        await _build(VMB4DC, year=None, week=None)

    assert _mismatch_warnings(caplog) == []


@pytest.mark.asyncio
async def test_outdated_module_is_flagged_for_home_assistant():
    """The mismatch is state, not only a log line, so HA can show it."""
    module = await _build(VMB4DC, year=18, week=2)

    assert module.is_memory_map_outdated() is True
    assert module.get_build() == "1802"
    assert module.get_memory_map_build() == "1915"


@pytest.mark.asyncio
async def test_current_module_is_not_flagged():
    """A module on current firmware carries no flag."""
    module = await _build(VMB4DC, year=25, week=1)

    assert module.is_memory_map_outdated() is False
    assert module.get_memory_map_build() == "1915"


@pytest.mark.asyncio
async def test_writes_are_refused_on_an_outdated_module():
    """Writing would corrupt the module, so it must fail loudly."""
    module = await _build(VMB4DC, year=18, week=2)
    memory = module.get_memory()

    assert memory.writes_blocked is True
    with pytest.raises(VelbusMemoryWriteBlocked):
        await memory.write_byte(0x00E0, 0x41)
    with pytest.raises(VelbusMemoryWriteBlocked):
        await memory.write_bytes(0x00E0, b"ABCD")


@pytest.mark.asyncio
async def test_writes_are_allowed_on_a_current_module():
    """The guard must not block modules that are fine."""
    module = await _build(VMB4DC, year=25, week=1)

    assert module.get_memory().writes_blocked is False


@pytest.mark.asyncio
async def test_writes_are_allowed_when_no_build_is_declared():
    """Specs without a declared build can never block writes."""
    module = await _build(VMBLCDWB, year=10, week=1)

    assert module.is_memory_map_outdated() is False
    assert module.get_memory().writes_blocked is False


def test_declared_builds_are_four_digit_strings():
    """MemoryMapBuild is a zero padded "YYWW" string, never an int."""
    for path in sorted(glob.glob(os.path.join(SPEC_DIR, "*.json"))):
        spec = json.loads(pathlib.Path(path).read_text())
        if "MemoryMapBuild" not in spec:
            continue
        value = spec["MemoryMapBuild"]
        assert isinstance(value, str), (
            f"{os.path.basename(path)}: MemoryMapBuild is "
            f"{type(value).__name__}, expected str"
        )
        assert re.fullmatch(r"\d{4}", value), (
            f"{os.path.basename(path)}: MemoryMapBuild {value!r} is not YYWW"
        )
