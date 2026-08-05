"""Tests for reading every action table and keeping it on disk."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from velbusaio.action_cache import (
    action_ranges,
    cached_actions,
    clear_action_cache,
    export_module_actions,
    import_module_actions,
    load_action_cache,
    save_action_cache,
    scan_actions,
    scan_module_actions,
)
from velbusaio.actions import build_action_tables
from velbusaio.memory import MemoryBackend, join_address
from velbusaio.messages.memory_data import MemoryDataMessage
from velbusaio.messages.memory_data_block import MemoryDataBlockMessage
from velbusaio.messages.read_data_block_from_memory import (
    ReadDataBlockFromMemoryMessage,
)
from velbusaio.messages.read_data_from_memory import ReadDataFromMemoryMessage

# One relay channel with two programmed slots, the rest unused.
_SPEC = {
    "slot_count": 4,
    "slot_size": 6,
    "actions": "relay_classic",
    "channels": {
        "01": {"bank": "0000", "noc_address": "00EA"},
        "02": {"bank": "0100", "noc_address": "01EA"},
    },
}
_SHARED_SPEC = {
    "layout": "shared",
    "slot_count": 4,
    "slot_size": 7,
    "actions": "relay_v2",
    "bank": "00E8",
    "subject_encoding": "param4",
    "channels": {"01": {}, "02": {}, "03": {}},
}


class FakeModule:
    """A module with real action tables over a dict-backed bus."""

    def __init__(
        self,
        address: int,
        spec: dict | None = None,
        *,
        serial: str = "0001",
        store: dict[int, int] | None = None,
    ) -> None:
        """Build the module and the bus answering for it."""
        self._address = address
        self._serial = serial
        self.store: dict[int, int] = store if store is not None else {}
        self.reads = 0
        self.writer = AsyncMock(side_effect=self._respond)
        self.memory = MemoryBackend(address, self.writer, timeout=1.0)
        self.tables = build_action_tables(self.memory, spec or _SPEC)

    async def _respond(self, msg) -> None:
        if isinstance(msg, ReadDataBlockFromMemoryMessage):
            self.reads += 1
            addr = join_address(msg.high_address, msg.low_address)
            reply = MemoryDataBlockMessage(self._address)
            reply.high_address = msg.high_address
            reply.low_address = msg.low_address
            reply.data = bytes(self.store.get(addr + i, 0xFF) for i in range(4))
            self.memory.feed_message(reply)
        elif isinstance(msg, ReadDataFromMemoryMessage):
            self.reads += 1
            addr = join_address(msg.high_address, msg.low_address)
            reply = MemoryDataMessage(self._address)
            reply.high_address = msg.high_address
            reply.low_address = msg.low_address
            reply.data = self.store.get(addr, 0xFF)
            self.memory.feed_message(reply)

    def program(self, address: int, data: bytes) -> None:
        """Put slot bytes in the module's eeprom."""
        for offset, value in enumerate(data):
            self.store[address + offset] = value

    def get_address(self) -> int:
        """Return the module address."""
        return self._address

    def get_name(self) -> str:
        """Return the module name."""
        return f"Module {self._address}"

    def get_type(self) -> int:
        """Return the module type id."""
        return 0x1D

    def get_type_name(self) -> str:
        """Return the module type name."""
        return "VMB4RYLD"

    def get_serial(self) -> str:
        """Return the module serial."""
        return self._serial

    def get_sw_version(self) -> str:
        """Return the firmware build."""
        return "1234"

    def get_memory_map_build(self) -> str:
        """Return the memory map build."""
        return "1234"

    def get_memory(self) -> MemoryBackend:
        """Return the memory backend."""
        return self.memory

    def get_action_tables(self) -> dict:
        """Return the action tables."""
        return dict(self.tables)


class FakeController:
    """Just enough controller for the cache helpers."""

    def __init__(self, cache_dir, *modules: FakeModule) -> None:
        """Hold the modules and the cache directory."""
        self._cache_dir = str(cache_dir)
        self._modules = {module.get_address(): module for module in modules}

    def get_cache_dir(self) -> str:
        """Return the cache directory."""
        return self._cache_dir

    def get_modules(self) -> dict:
        """Return the modules."""
        return dict(self._modules)


def _programmed_module(address: int = 0x11) -> FakeModule:
    module = FakeModule(address)
    module.program(0x0000, bytes([0x05, 0x01, 0x09, 0xFF, 0xFF, 0xFF]))
    module.program(0x0006, bytes([0x06, 0x02, 0x01, 0xFF, 0xFF, 0xFF]))
    return module


class TestActionRanges:
    """Tests for the eeprom ranges a scan has to read."""

    def test_per_channel_ranges_include_no_nc(self):
        """Test Per channel ranges include no nc."""
        module = FakeModule(0x11)
        assert action_ranges(module) == [
            (0x0000, 24),
            (0x00EA, 1),
            (0x0100, 24),
            (0x01EA, 1),
        ]

    def test_shared_table_is_listed_once(self):
        """A shared table read once per channel would triple the scan."""
        module = FakeModule(0x26, _SHARED_SPEC)
        assert action_ranges(module) == [(0x00E8, 28)]


class TestScan:
    """Tests for reading the tables."""

    @pytest.mark.asyncio
    async def test_scan_returns_programmed_slots(self):
        """Test Scan returns programmed slots."""
        module = _programmed_module()
        result = await scan_module_actions(module)
        assert result.action_count == 2
        assert [slot.source_address for slot in result.channels[1]] == [0x05, 0x06]
        assert result.channels[2] == []
        assert result.from_cache is False

    @pytest.mark.asyncio
    async def test_second_scan_costs_no_bus_traffic(self):
        """Test Second scan costs no bus traffic."""
        module = _programmed_module()
        await scan_module_actions(module)
        reads = module.reads
        assert reads > 0
        result = await scan_module_actions(module)
        assert module.reads == reads
        assert result.from_cache is True

    @pytest.mark.asyncio
    async def test_force_rereads_the_module(self):
        """Test Force rereads the module."""
        module = _programmed_module()
        await scan_module_actions(module)
        reads = module.reads
        module.program(0x0000, bytes([0x07, 0x01, 0x09, 0xFF, 0xFF, 0xFF]))
        result = await scan_module_actions(module, force=True)
        assert module.reads > reads
        assert result.channels[1][0].source_address == 0x07

    @pytest.mark.asyncio
    async def test_scan_reports_progress_per_module(self, tmp_path):
        """Test Scan reports progress per module."""
        controller = FakeController(
            tmp_path, _programmed_module(0x11), _programmed_module(0x12)
        )
        seen = []
        scan = await scan_actions(controller, progress=seen.append)

        # Both units: modules for the whole run, bytes for the module in hand.
        # Reading one module is one module either way, so without the bytes
        # there would be nothing to show while it works.
        assert (seen[0].done, seen[0].total) == (0, 2)
        assert (seen[-1].done, seen[-1].total) == (2, 2)
        assert seen[0].bytes_done == 0
        first = [step for step in seen if step.address == 0x11]
        assert first[-1].bytes_done == first[-1].bytes_total > 0
        assert first == sorted(first, key=lambda step: step.bytes_done)
        assert set(scan.modules) == {0x11, 0x12}
        assert scan.action_count == 4

    @pytest.mark.asyncio
    async def test_a_forced_scan_counts_from_zero(self, tmp_path):
        """What it already holds says nothing about a read that starts over."""
        module = _programmed_module()
        await scan_module_actions(module)
        controller = FakeController(tmp_path, module)

        seen = []
        await scan_actions(controller, force=True, progress=seen.append)
        assert seen[0].bytes_done == 0
        assert seen[-1].bytes_done == seen[-1].bytes_total > 0

    @pytest.mark.asyncio
    async def test_one_dead_module_does_not_stop_the_scan(self, tmp_path):
        """A module that stops answering must not cost the whole installation."""
        dead = FakeModule(0x12)
        dead.memory._timeout = 0.01  # noqa: SLF001 - keep the test short
        dead.writer.side_effect = None  # never answers
        controller = FakeController(tmp_path, _programmed_module(0x11), dead)

        scan = await scan_actions(controller)
        assert scan.modules[0x11].action_count == 2
        assert set(scan.errors) == {0x12}
        assert scan.modules[0x12].action_count == 0

    @pytest.mark.asyncio
    async def test_addresses_limits_the_scan(self, tmp_path):
        """Test Addresses limits the scan."""
        other = _programmed_module(0x12)
        controller = FakeController(tmp_path, _programmed_module(0x11), other)
        scan = await scan_actions(controller, addresses=[0x11])
        assert set(scan.modules) == {0x11}
        assert other.reads == 0

    @pytest.mark.asyncio
    async def test_cached_actions_leaves_unscanned_modules_alone(self, tmp_path):
        """Drawing a page must not start a minutes-long read behind the user."""
        scanned = _programmed_module(0x11)
        await scan_module_actions(scanned)
        unscanned = _programmed_module(0x12)
        controller = FakeController(tmp_path, scanned, unscanned)

        scan = await cached_actions(controller)
        assert set(scan.modules) == {0x11}
        assert unscanned.reads == 0


class TestPersistence:
    """Tests for keeping the scan across a restart."""

    @pytest.mark.asyncio
    async def test_roundtrip_restores_slots_without_the_bus(self, tmp_path):
        """Test Roundtrip restores slots without the bus."""
        module = _programmed_module()
        await scan_module_actions(module)
        controller = FakeController(tmp_path, module)
        assert await save_action_cache(controller) == [0x11]

        # A fresh module, as after a restart: same eeprom, empty memory cache.
        restarted = FakeModule(0x11, store=dict(module.store))
        fresh = FakeController(tmp_path, restarted)
        loaded = await load_action_cache(fresh)
        assert set(loaded) == {0x11}

        result = await scan_module_actions(restarted)
        assert restarted.reads == 0
        assert result.from_cache is True
        assert [slot.source_address for slot in result.channels[1]] == [0x05, 0x06]

    @pytest.mark.asyncio
    async def test_unread_module_is_not_written(self, tmp_path):
        """A failed scan must not overwrite an earlier good one with nothing."""
        controller = FakeController(tmp_path, _programmed_module())
        assert await save_action_cache(controller) == []

    @pytest.mark.asyncio
    async def test_another_module_at_the_same_address_is_rejected(self, tmp_path):
        """Test Another module at the same address is rejected."""
        module = _programmed_module()
        await scan_module_actions(module)
        data = export_module_actions(module)

        replacement = FakeModule(0x11, serial="9999")
        assert import_module_actions(replacement, data) is None

    @pytest.mark.asyncio
    async def test_partial_read_is_not_cached(self, tmp_path):
        """Test Partial read is not cached."""
        module = _programmed_module()
        await scan_module_actions(module)
        module.memory.invalidate(0x0100, 0x0100)
        data = export_module_actions(module)
        assert [block["start"] for block in data["blocks"]] == [0x0000, 0x00EA, 0x01EA]

    @pytest.mark.asyncio
    async def test_a_moved_table_is_ignored(self, tmp_path):
        """A spec change moves the table; the old bytes no longer describe it."""
        module = _programmed_module()
        await scan_module_actions(module)
        data = export_module_actions(module)
        data["blocks"][0]["start"] = 0x0200
        assert import_module_actions(FakeModule(0x11), data) is not None

    @pytest.mark.asyncio
    async def test_clear_forces_the_next_scan_back_onto_the_bus(self, tmp_path):
        """Test Clear forces the next scan back onto the bus."""
        module = _programmed_module()
        await scan_module_actions(module)
        controller = FakeController(tmp_path, module)
        await save_action_cache(controller)

        assert await clear_action_cache(controller) == [0x11]
        assert not list(tmp_path.glob("*-actions.json"))

        module.reads = 0
        await scan_module_actions(module)
        assert module.reads > 0
