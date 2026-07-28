"""The auto send interval byte, shared by the temperature and light requests.

A module is told how often to put a sensor value on the bus with a single byte,
and Velbus uses the same encoding for the temperature request (``0xE5``) and the
light value request (``0xAA``):

    0        leave the current setting alone; the message is a plain request
    1..4     auto send disabled
    5..9     auto send on every change, with 5..9 s as the minimum interval
    10..255  auto send at this fixed interval, in seconds
"""

from __future__ import annotations

from typing import Final, Literal

AUTOSEND_NO_CHANGE: Final = 0
AUTOSEND_DISABLED: Final = 1
AUTOSEND_ON_CHANGE: Final = 5
AUTOSEND_INTERVAL_MIN: Final = 10
AUTOSEND_INTERVAL_MAX: Final = 255

AutosendMode = Literal["never", "on_change", "interval"]
AUTOSEND_MODES: Final = ("never", "on_change", "interval")

# The byte is not a plain number of seconds, so anything offering it for
# editing has to say what the low values mean.
AUTOSEND_HINT: Final = (
    "0 keeps the current setting, 1-4 turns it off, 5-9 sends on every change, "
    "10-255 is a fixed interval in seconds"
)


def encode_autosend_interval(mode: str, seconds: int | None = None) -> int:
    """Return the interval byte that puts a module in the requested mode."""
    if mode == "never":
        return AUTOSEND_DISABLED
    if mode == "on_change":
        return AUTOSEND_ON_CHANGE
    if mode == "interval":
        if seconds is None:
            raise ValueError("seconds is required when mode is 'interval'")
        if not AUTOSEND_INTERVAL_MIN <= seconds <= AUTOSEND_INTERVAL_MAX:
            raise ValueError(
                "seconds must be between "
                f"{AUTOSEND_INTERVAL_MIN} and {AUTOSEND_INTERVAL_MAX}"
            )
        return seconds
    raise ValueError(
        f"Unknown autosend mode: {mode!r} "
        f"(expected {', '.join(repr(item) for item in AUTOSEND_MODES)})"
    )


def decode_autosend_interval(value: int) -> tuple[str, int | None]:
    """Return the (mode, seconds) a module reports through an interval byte.

    ``seconds`` is only meaningful for a fixed interval; in the other modes
    there is no interval to report and it is None. A byte of 0 means the module
    was never told anything, which reads as "unknown" rather than a mode.
    """
    if value == AUTOSEND_NO_CHANGE:
        return "unknown", None
    if value < AUTOSEND_ON_CHANGE:
        return "never", None
    if value < AUTOSEND_INTERVAL_MIN:
        return "on_change", None
    return "interval", value
