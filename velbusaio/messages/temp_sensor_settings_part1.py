"""TempSensorSettingsPart1 message class.

:author: Maikel Punie <maikel.punie@gmail.com>
"""

from __future__ import annotations

from velbusaio.command_registry import register
from velbusaio.message_fields import DeclarativeMessage, HalfDegreeField

COMMAND_CODE = 0xE8


@register(COMMAND_CODE)
class TempSensorSettingsPart1(DeclarativeMessage):
    """First part of temperature sensor settings (heating presets)."""

    _command_code = COMMAND_CODE
    _data_length = 7

    current_set = HalfDegreeField(0)
    comfort_heating = HalfDegreeField(1)
    day_heating = HalfDegreeField(2)
    night_heating = HalfDegreeField(3)
    antifreeze_heating = HalfDegreeField(4)
    temp_difference = HalfDegreeField(5)
    hysteresis = HalfDegreeField(6, signed=False)
