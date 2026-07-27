"""Test cases for the reserved-memory guard around action tables."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest

from velbusaio.actions import build_action_tables, reserved_ranges
from velbusaio.memory import MemoryBackend

# The VMB4RYLD layout that shipped before the fix: a table sized for firmware
# that predates the module name, combined with the name that only the later
# firmware has. Slots 37 and 38 and the NO/NC byte land inside the name.
BROKEN_RELAY_SPEC = {
    "actions": "relay_classic",
    "slot_count": 39,
    "slot_size": 6,
    "channels": {
        "01": {"bank": "0000", "noc_address": "00EA"},
        "02": {"bank": "0100", "noc_address": "01EA"},
    },
}
RELAY_MEMORY = {
    "ModuleName": "00E3-00EF;01E3-01EF",
    "Channels": {"01": "00F0-00FF", "02": "01F0-01FF"},
    "ActionTable": BROKEN_RELAY_SPEC,
}


@pytest.fixture(name="backend")
def backend_fixture() -> MemoryBackend:
    """Return a memory backend with a stubbed writer."""
    return MemoryBackend(0x20, AsyncMock())


class TestReservedRanges:
    """Test cases for reserved_ranges()."""

    def test_collects_module_and_channel_names(self) -> None:
        """Both the module name and every channel name are protected."""
        assert reserved_ranges(RELAY_MEMORY) == [
            (0x00E3, 0x00EF),
            (0x01E3, 0x01EF),
            (0x00F0, 0x00FF),
            (0x01F0, 0x01FF),
        ]

    @pytest.mark.parametrize(
        "spec", [None, {}, {"ModuleName": ""}, {"ModuleName": "garbage"}]
    )
    def test_missing_or_unparsable_yields_nothing(self, spec) -> None:
        """A spec without usable ranges guards nothing rather than raising."""
        assert reserved_ranges(spec) == []


class TestActionTableGuard:
    """Test cases for the guard applied in build_action_tables()."""

    def test_slots_are_clamped_to_reserved_memory(self, backend) -> None:
        """Slots that would reach into the name are dropped.

        The name starts at 0x00E3, so with 6-byte slots only 37 fit (0..36,
        ending at 0x00DD). Slots 37 and 38 would have run to 0x00E9.
        """
        tables = build_action_tables(
            backend, BROKEN_RELAY_SPEC, reserved=reserved_ranges(RELAY_MEMORY)
        )

        assert tables[1].slot_count == 37
        assert tables[1].bank + tables[1].slot_count * tables[1].slot_size - 1 < 0x00E3

    def test_guard_applies_per_bank(self, backend) -> None:
        """Each channel is measured against the reserved range in its own bank."""
        tables = build_action_tables(
            backend, BROKEN_RELAY_SPEC, reserved=reserved_ranges(RELAY_MEMORY)
        )

        assert tables[2].slot_count == 37
        assert tables[2].bank + tables[2].slot_count * tables[2].slot_size - 1 < 0x01E3

    def test_colliding_noc_address_is_dropped(self, backend) -> None:
        """A NO/NC byte inside the name is never read or written."""
        tables = build_action_tables(
            backend, BROKEN_RELAY_SPEC, reserved=reserved_ranges(RELAY_MEMORY)
        )

        assert tables[1].noc_address is None
        assert tables[2].noc_address is None

    def test_guard_warns_about_what_it_dropped(self, backend, caplog) -> None:
        """The operator gets told, so a wrong spec is visible rather than silent."""
        caplog.set_level(logging.WARNING)
        build_action_tables(
            backend, BROKEN_RELAY_SPEC, reserved=reserved_ranges(RELAY_MEMORY)
        )

        messages = " ".join(r.getMessage() for r in caplog.records)
        assert "only 37 fit before reserved memory" in messages
        assert "NO/NC address 0x00EA" in messages

    def test_correct_spec_is_left_alone(self, backend, caplog) -> None:
        """A spec that already agrees with the firmware keeps every slot."""
        caplog.set_level(logging.WARNING)
        spec = {
            **BROKEN_RELAY_SPEC,
            "slot_count": 36,
            "channels": {
                "01": {"bank": "0000", "noc_address": "00D8"},
                "02": {"bank": "0100", "noc_address": "01D8"},
            },
        }

        tables = build_action_tables(
            backend, spec, reserved=reserved_ranges(RELAY_MEMORY)
        )

        assert tables[1].slot_count == 36
        assert tables[1].noc_address == 0x00D8
        assert caplog.records == []

    def test_without_reserved_nothing_is_clamped(self, backend) -> None:
        """The guard is opt-in, so existing callers keep their behaviour."""
        tables = build_action_tables(backend, BROKEN_RELAY_SPEC)

        assert tables[1].slot_count == 39
        assert tables[1].noc_address == 0x00EA

    def test_shared_table_is_clamped_once(self, backend, caplog) -> None:
        """A table shared by every channel is measured against its single bank."""
        caplog.set_level(logging.WARNING)
        spec = {
            "actions": "input_v2",
            "layout": "shared",
            "subject_encoding": "param2",
            "bank": "0100",
            "slot_count": 60,
            "slot_size": 5,
            "channels": {"01": {}, "02": {}},
        }

        tables = build_action_tables(backend, spec, reserved=[(0x0200, 0x023F)])

        # 0x0100 up to 0x01FF is 256 bytes, so 51 five-byte slots fit.
        assert tables[1].slot_count == 51
        assert tables[2].slot_count == 51
        assert "only 51 fit before reserved memory" in caplog.text
