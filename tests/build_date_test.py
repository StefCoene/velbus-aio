"""Test cases for decoding the build date a module reports."""

from __future__ import annotations

import logging

import pytest

from velbusaio.build_date import decode_build

# Every distinct build date observed across two real installations, with the
# bytes as they came off the bus. The switch from binary to BCD sits between
# 1927 and 2051; note that VMB4RYLD and VMB4RYNO appear on both sides of it,
# so the encoding follows the firmware generation, not the module type.
OBSERVED = [
    # bytes,        year, week, build,  modules
    ((0x12, 0x16), 18, 22, "1822", "VMB6PBN, VMB8PBU"),
    ((0x13, 0x0F), 19, 15, "1915", "VMBDMI-R"),
    ((0x13, 0x1B), 19, 27, "1927", "VMB4RYLD, VMB4RYNO"),
    ((0x20, 0x51), 20, 51, "2051", "VMBPIRO"),
    ((0x22, 0x21), 22, 21, "2221", "VMBGP4"),
    ((0x23, 0x06), 23, 6, "2306", "VMB7IN"),
    ((0x23, 0x07), 23, 7, "2307", "VMB2BLE"),
    ((0x24, 0x36), 24, 36, "2436", "VMB4RYLD, VMB4RYNO"),
    ((0x24, 0x46), 24, 46, "2446", "VMB4DC"),
    ((0x25, 0x11), 25, 11, "2511", "VMBPIRM"),
    ((0x26, 0x13), 26, 13, "2613", "VMBGPOD"),
]


@pytest.mark.parametrize(
    ("raw", "year", "week"),
    [(raw, year, week) for raw, year, week, _build, _mods in OBSERVED],
    ids=[f"{build}-{mods}" for _raw, _y, _w, build, mods in OBSERVED],
)
def test_observed_build_dates(raw: tuple[int, int], year: int, week: int) -> None:
    """Every build date seen on a real bus decodes to its documented value."""
    assert decode_build(*raw) == (year, week)


class TestEncodingIsUnambiguous:
    """The two readings must never both be valid, or the choice is a guess."""

    def test_bcd_is_chosen_when_binary_year_is_impossible(self) -> None:
        """0x24 0x46 as binary is year 36 week 70, and there is no week 70."""
        assert decode_build(0x24, 0x46) == (24, 46)

    def test_binary_is_chosen_when_bcd_is_not_valid_bcd(self) -> None:
        """Week byte 0x1B has a low nibble of B, which is not a decimal digit."""
        assert decode_build(0x13, 0x1B) == (19, 27)

    def test_binary_is_chosen_when_bcd_year_predates_the_switch(self) -> None:
        """0x12 0x16 reads as both 2012w16 and 2018w22; only the era decides.

        This is the case a plausibility check alone cannot settle. BCD did not
        exist in 2012, so the binary reading is the only possible one.
        """
        assert decode_build(0x12, 0x16) == (18, 22)

    def test_bcd_year_at_the_switch_is_bcd(self) -> None:
        """Year 20 is the first BCD year, so 0x20 is 2020 and not 2032."""
        assert decode_build(0x20, 0x51) == (20, 51)

    def test_last_binary_year_is_binary(self) -> None:
        """Year byte 19 is the last binary year, not BCD 13."""
        assert decode_build(19, 27) == (19, 27)


class TestImplausibleInput:
    """A byte pair that fits neither encoding must not raise."""

    def test_unknown_encoding_falls_back_to_the_raw_bytes(self) -> None:
        """0x18 0x2A is BCD year 18 (too early) and binary year 24 (too late)."""
        assert decode_build(0x18, 0x2A) == (0x18, 0x2A)

    def test_the_fallback_is_reported(self, caplog) -> None:
        """A build we cannot read is worth a log line, not silence."""
        decode_build.cache_clear()
        with caplog.at_level(logging.DEBUG, logger="velbus-build-date"):
            decode_build(0x18, 0x2A)

        assert "0x18 0x2A" in caplog.text
        assert "build 2442" in caplog.text

    @pytest.mark.parametrize("week", [0x00, 0x54, 0x99, 0xFF])
    def test_week_zero_and_beyond_53_are_not_dates(self, week: int) -> None:
        """Weeks run 1..53; anything else means we read the byte wrong."""
        assert decode_build(0x24, week) == (0x24, week)

    def test_a_year_in_the_future_is_not_a_date(self) -> None:
        """BCD year 99 cannot be a build that already exists."""
        assert decode_build(0x99, 0x20) == (0x99, 0x20)
