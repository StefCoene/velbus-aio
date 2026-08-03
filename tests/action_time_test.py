"""Tests for the action time parameter table."""

from __future__ import annotations

import pytest

from velbusaio.action_time import (
    INFINITE,
    decode_action_time,
    encode_action_time,
    format_action_time,
    iter_action_times,
)

# Every row the protocol documentation prints, as (byte, seconds). The table
# itself is elided with "..." between these, so these are the only values the
# documentation actually states and each one pins a segment boundary.
DOCUMENTED = [
    (0, 0),  # no timer or fastest dim time
    (1, 1),
    (2, 2),
    (119, 119),  # 1min59s
    (120, 120),  # 2min
    (121, 135),  # 2min15s
    (131, 285),  # 4min45s
    (132, 300),  # 5min
    (133, 330),  # 5min30s
    (181, 1770),  # 29min30s
    (182, 1800),  # 30min
    (183, 1860),  # 31min
    (211, 3540),  # 59min
    (212, 3600),  # 1h
    (213, 4500),  # 1h15min
    (227, 17100),  # 4h45min
    (228, 18000),  # 5h
    (229, 19800),  # 5h30min
    (237, 34200),  # 9h30min
    (238, 36000),  # 10h
    (239, 39600),  # 11h
    (251, 82800),  # 23h
    (252, 86400),  # 1d
    (253, 172800),  # 2d
    (254, 259200),  # 3d
]


@pytest.mark.parametrize(("value", "seconds"), DOCUMENTED)
def test_decode_matches_the_documented_table(value: int, seconds: int) -> None:
    """Every duration the documentation names decodes to that duration."""
    assert decode_action_time(value) == seconds


@pytest.mark.parametrize(("value", "seconds"), DOCUMENTED)
def test_a_documented_duration_encodes_back_to_its_own_byte(
    value: int, seconds: int
) -> None:
    """A duration that exists in the table is stored as itself, not a neighbour."""
    assert encode_action_time(seconds) == value


def test_the_table_never_goes_backwards() -> None:
    """Durations rise with the byte, so a higher byte is never a shorter time."""
    seconds = [decode_action_time(value) for value in range(INFINITE)]
    assert seconds == sorted(seconds)
    assert len(set(seconds)) == len(seconds)


def test_infinite_is_its_own_value() -> None:
    """0xFF means the action does not time out, not a duration of 255."""
    assert decode_action_time(INFINITE) is None
    assert encode_action_time(None) == INFINITE
    assert format_action_time(None) == "infinite"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (150, 122),  # 2min30s exists, between the 15s steps
        (149, 122),  # rounds to the nearest step, not down
        (128, 121),  # 2min08s sits between 2min and 2min15s
        (400_000, 254),  # beyond three days there is nothing left but the last entry
    ],
)
def test_a_duration_between_two_entries_rounds_to_the_nearest(
    seconds: int, expected: int
) -> None:
    """A module holds fixed durations, so anything else moves to the closest one."""
    assert encode_action_time(seconds) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0s"),
        (119, "1min59s"),
        (285, "4min45s"),
        (1770, "29min30s"),
        (4500, "1h15min"),
        (82800, "23h"),
        (259200, "3d"),
    ],
)
def test_labels_read_like_the_documentation(seconds: int, expected: str) -> None:
    """The label is what the documentation prints for that row."""
    assert format_action_time(seconds) == expected


def test_the_option_list_covers_every_byte() -> None:
    """A UI list offers all 256 values a module can hold, infinite included."""
    options = list(iter_action_times())
    assert len(options) == 256
    assert options[0] == {"value": 0, "seconds": 0, "label": "0s"}
    assert options[-1] == {"value": 255, "seconds": None, "label": "infinite"}


@pytest.mark.parametrize("value", [-1, 256])
def test_a_value_outside_a_byte_is_refused(value: int) -> None:
    """Nothing outside a byte can come off the bus, so it is a programming error."""
    with pytest.raises(ValueError, match="not a byte"):
        decode_action_time(value)


def test_a_negative_duration_is_refused() -> None:
    """There is no byte for a negative time."""
    with pytest.raises(ValueError, match="cannot be negative"):
        encode_action_time(-1)
