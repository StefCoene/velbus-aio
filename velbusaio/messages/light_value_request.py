"""Light Value Request message class.

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

COMMAND_CODE = 0xAA

# DATABYTE2 of COMMAND_LIGHT_VALUE_REQUEST configures how often a module with a
# light sensor auto-sends its light value onto the bus, in the same encoding the
# temperature request uses. Re-exported here so callers can reach the light
# constants through the light message.
LIGHT_AUTOSEND_NO_CHANGE = AUTOSEND_NO_CHANGE
LIGHT_AUTOSEND_DISABLED = AUTOSEND_DISABLED
LIGHT_AUTOSEND_ON_CHANGE = AUTOSEND_ON_CHANGE
LIGHT_AUTOSEND_INTERVAL_MIN = AUTOSEND_INTERVAL_MIN
LIGHT_AUTOSEND_INTERVAL_MAX = AUTOSEND_INTERVAL_MAX


@register(COMMAND_CODE)
class LightValueRequest(DeclarativeMessage):
    """Light Value Request message.

    When ``autosend_interval`` is ``None`` (the default) the message is a plain
    light value request consisting of a single command byte. When an interval is
    supplied it is sent as DATABYTE2 to (re)configure how often the module
    reports its light value on the bus (see the ``LIGHT_AUTOSEND_*`` constants).
    """

    _command_code = COMMAND_CODE

    def __init__(self, address=None, autosend_interval=None):
        """Initialize LightValueRequest instance."""
        super().__init__(address)
        self.autosend_interval = autosend_interval

    def data_to_binary(self):
        """:return: bytes"""
        if self.autosend_interval is None:
            return bytes([COMMAND_CODE])
        return bytes([COMMAND_CODE, self.autosend_interval & 0xFF])
