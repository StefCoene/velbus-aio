"""Decode the firmware build date a module reports.

A module reports its build as two bytes: a year and a week. That is not the
same as two numbers. Older firmware sends them as plain binary, newer firmware
sends BCD, where each nibble is one decimal digit. So 0x24 0x46 is not year 36
week 70 -- there is no week 70 -- but build 2446, week 46 of 2024, which is
exactly what VelbusLink shows for such a module.

Nothing in the frame says which encoding was used, and a plausibility check on
its own does not settle it either: 0x12 0x16 reads as 2012 week 16 in BCD and
as 2018 week 22 in binary, and both are perfectly possible dates.

What does settle it is when the encoding changed. Every module observed on
build 1927 and earlier uses binary, every module on 2051 and later uses BCD,
including the same module types on both sides of that line. So a binary year
can only be 19 or lower and a BCD year only 20 or higher. Those ranges do not
overlap, which means at most one reading of a byte pair can be valid.
"""

from __future__ import annotations

from datetime import datetime
from functools import cache
import logging

# Velbus switched from binary to BCD build dates between build 1927 and 2051.
BCD_FROM_YEAR = 20
# ISO 8601 allows a 53rd week; no module can report more.
MAX_WEEK = 53

_LOGGER = logging.getLogger("velbus-build-date")


def _bcd(value: int) -> int | None:
    """Return the BCD reading of a byte, or None when it is not valid BCD."""
    high, low = value >> 4, value & 0x0F
    if high > 9 or low > 9:
        return None
    return high * 10 + low


def _plausible(year: int, week: int, *, bcd: bool) -> bool:
    """Whether a year/week reading can be a real build date in this encoding."""
    if not 1 <= week <= MAX_WEEK:
        return False
    if bcd:
        return BCD_FROM_YEAR <= year <= datetime.now().year % 100
    return year < BCD_FROM_YEAR


@cache
def decode_build(year_byte: int, week_byte: int) -> tuple[int, int]:
    """Return the build date as (year, week), both as decimal numbers.

    When neither encoding yields a plausible date the bytes are returned
    unchanged, so a module with an encoding we do not know about still gets a
    build number instead of an exception. The cache keeps that report to one
    line per distinct byte pair; the domain is 65536 pairs at most and the
    function is pure.
    """
    year_bcd, week_bcd = _bcd(year_byte), _bcd(week_byte)
    if (
        year_bcd is not None
        and week_bcd is not None
        and _plausible(year_bcd, week_bcd, bcd=True)
    ):
        return year_bcd, week_bcd

    if _plausible(year_byte, week_byte, bcd=False):
        return year_byte, week_byte

    _LOGGER.debug(
        "Build date bytes 0x%02X 0x%02X are neither a plausible BCD nor binary "
        "date; reporting them unchanged as build %02d%02d",
        year_byte,
        week_byte,
        year_byte,
        week_byte,
    )
    return year_byte, week_byte
