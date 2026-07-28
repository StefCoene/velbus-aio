"""Test cases for the auto send interval byte."""

from __future__ import annotations

import pytest

from velbusaio.autosend import (
    AUTOSEND_DISABLED,
    AUTOSEND_ON_CHANGE,
    decode_autosend_interval,
    encode_autosend_interval,
)


class TestEncode:
    """Test cases for encode_autosend_interval()."""

    @pytest.mark.parametrize(
        ("mode", "seconds", "expected"),
        [
            ("never", None, AUTOSEND_DISABLED),
            ("on_change", None, AUTOSEND_ON_CHANGE),
            ("interval", 10, 10),
            ("interval", 60, 60),
            ("interval", 255, 255),
        ],
    )
    def test_modes(self, mode: str, seconds: int | None, expected: int) -> None:
        """Each mode maps to the byte the protocol documents."""
        assert encode_autosend_interval(mode, seconds) == expected

    def test_interval_requires_seconds(self) -> None:
        """An interval without a length cannot be encoded."""
        with pytest.raises(ValueError, match="seconds is required"):
            encode_autosend_interval("interval")

    @pytest.mark.parametrize("seconds", [0, 1, 4, 9, 256])
    def test_interval_outside_the_valid_range(self, seconds: int) -> None:
        """Below 10 the byte would mean a different mode entirely."""
        with pytest.raises(ValueError, match="must be between 10 and 255"):
            encode_autosend_interval("interval", seconds)

    def test_unknown_mode(self) -> None:
        """An unknown mode names the ones that do exist."""
        with pytest.raises(ValueError, match="Unknown autosend mode"):
            encode_autosend_interval("sometimes")


class TestDecode:
    """Test cases for decode_autosend_interval()."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (0, ("unknown", None)),
            (1, ("never", None)),
            (4, ("never", None)),
            (5, ("on_change", None)),
            (9, ("on_change", None)),
            (10, ("interval", 10)),
            (60, ("interval", 60)),
            (255, ("interval", 255)),
        ],
    )
    def test_every_range(self, value: int, expected: tuple[str, int | None]) -> None:
        """Every documented range decodes to its mode."""
        assert decode_autosend_interval(value) == expected

    def test_round_trip(self) -> None:
        """What encode writes, decode reads back."""
        for mode, seconds in (("never", None), ("on_change", None), ("interval", 45)):
            assert decode_autosend_interval(
                encode_autosend_interval(mode, seconds)
            ) == (mode, seconds)
