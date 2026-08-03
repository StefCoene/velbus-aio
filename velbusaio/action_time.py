"""The time parameters of an action slot.

A slot stores its times as a single byte that is not a number of seconds but an
index into a table the modules share. The table is piecewise linear: it counts
seconds up to two minutes, then quarter minutes, then half minutes, and so on
up to three days, with 255 meaning the action never times out.

The protocol documentation prints only the boundaries of each piece and elides
the rest, so the pieces are written out here and the tests pin every boundary
the documentation does give.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Final

# (first index, last index, seconds at the first index, seconds per step)
_SEGMENTS: Final = (
    (0, 119, 0, 1),
    (120, 131, 120, 15),
    (132, 181, 300, 30),
    (182, 211, 1800, 60),
    (212, 227, 3600, 900),
    (228, 237, 18000, 1800),
    (238, 251, 36000, 3600),
    (252, 254, 86400, 86400),
)

#: The byte that makes an action run until something else stops it.
INFINITE: Final = 0xFF

#: What an empty slot holds. It decodes as INFINITE, so an action that takes a
#: time parameter needs a deliberate value rather than this default.
UNSET: Final = 0xFF


def decode_action_time(value: int) -> int | None:
    """Return the seconds a time parameter stands for, None for infinite."""
    if value == INFINITE:
        return None
    if not 0 <= value < INFINITE:
        raise ValueError(f"Time parameter {value} is not a byte")
    for first, last, base, step in _SEGMENTS:
        if first <= value <= last:
            return base + (value - first) * step
    raise ValueError(f"Time parameter {value} falls outside the table")


def encode_action_time(seconds: int | None) -> int:
    """Return the byte for a number of seconds, rounded to what a module can hold.

    Not every duration exists in the table, so a value between two entries is
    rounded to the nearest one. Anything beyond three days becomes infinite.
    """
    if seconds is None:
        return INFINITE
    if seconds < 0:
        raise ValueError(f"A time parameter cannot be negative: {seconds}")
    best = 0
    best_difference = None
    for first, last, base, step in _SEGMENTS:
        # Where the duration would land in this piece, kept inside it.
        index = min(max(first + round((seconds - base) / step), first), last)
        difference = abs(base + (index - first) * step - seconds)
        if best_difference is None or difference < best_difference:
            best, best_difference = index, difference
    return best


def format_action_time(seconds: int | None) -> str:
    """Return a compact label for a duration, the way the documentation writes it."""
    if seconds is None:
        return "infinite"
    if seconds == 0:
        return "0s"
    parts = []
    for unit, size in (("d", 86400), ("h", 3600), ("min", 60), ("s", 1)):
        count, seconds = divmod(seconds, size)
        if count:
            parts.append(f"{count}{unit}")
    return "".join(parts)


def iter_action_times() -> Iterator[dict[str, object]]:
    """Yield every value a time parameter can take, for a UI option list.

    A module holds a fixed set of durations, so offering exactly those beats a
    free number that silently rounds to something the user did not pick.
    """
    for value in range(INFINITE + 1):
        seconds = decode_action_time(value)
        yield {
            "value": value,
            "seconds": seconds,
            "label": format_action_time(seconds),
        }
