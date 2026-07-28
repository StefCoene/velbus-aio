"""Sensor Temperature Request Message.

:author: Maikel Punie <maikel.punie@gmail.com>
"""

from __future__ import annotations

from velbusaio.autosend import (
    AUTOSEND_DISABLED,
    AUTOSEND_INTERVAL_MAX,
    AUTOSEND_INTERVAL_MIN,
    AUTOSEND_NO_CHANGE,
    AUTOSEND_ON_CHANGE,
)
from velbusaio.command_registry import register
from velbusaio.message_fields import DeclarativeMessage

COMMAND_CODE = 0xE5

# DATABYTE2 of COMMAND_SENSOR_TEMP_REQUEST configures how often a module with a
# temperature sensor auto-sends its temperature onto the bus, in the encoding
# described in velbusaio.autosend. Re-exported here so callers can reach the
# temperature constants through the temperature message.
TEMP_AUTOSEND_NO_CHANGE = AUTOSEND_NO_CHANGE
TEMP_AUTOSEND_DISABLED = AUTOSEND_DISABLED
TEMP_AUTOSEND_ON_CHANGE = AUTOSEND_ON_CHANGE
TEMP_AUTOSEND_INTERVAL_MIN = AUTOSEND_INTERVAL_MIN
TEMP_AUTOSEND_INTERVAL_MAX = AUTOSEND_INTERVAL_MAX


@register(COMMAND_CODE)
class SensorTempRequest(DeclarativeMessage):
    """Sensor Temperature Request Message.

    When ``autosend_interval`` is ``None`` (the default) the message is a plain
    temperature request consisting of a single command byte. When an interval is
    supplied it is sent as DATABYTE2 to (re)configure how often the module
    reports its temperature on the bus (see the ``TEMP_AUTOSEND_*`` constants).
    """

    _command_code = COMMAND_CODE

    def __init__(self, address=None, autosend_interval=None):
        """Initialize SensorTempRequest instance."""
        super().__init__(address)
        self.autosend_interval = autosend_interval

    def data_to_binary(self):
        """:return: bytes"""
        if self.autosend_interval is None:
            return bytes([COMMAND_CODE])
        return bytes([COMMAND_CODE, self.autosend_interval & 0xFF])
