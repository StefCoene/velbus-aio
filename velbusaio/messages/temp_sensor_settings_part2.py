"""TempSensorSettingsPart2 message implementation.

:author: Maikel Punie <maikel.punie@gmail.com>
"""

from __future__ import annotations

from velbusaio.command_registry import register
from velbusaio.message_fields import (
    ByteField,
    DeclarativeMessage,
    HalfDegreeField,
    Int16Field,
)

COMMAND_CODE = 0xE9


@register(COMMAND_CODE)
class TempSensorSettingsPart2(DeclarativeMessage):
    """Second part of temperature sensor settings (cooling + timers)."""

    _command_code = COMMAND_CODE
    _data_length = 7

    comfort_cooling = HalfDegreeField(0)
    day_cooling = HalfDegreeField(1)
    night_cooling = HalfDegreeField(2)
    safe_cooling = HalfDegreeField(3)
    default_sleep_timer = Int16Field(4, default=0)
    autosend_interval = ByteField(6, default=0)
