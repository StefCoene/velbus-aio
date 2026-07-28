"""TempSensorSettingsRequest message implementation.

:author: Maikel Punie <maikel.punie@gmail.com>
"""

from __future__ import annotations

from velbusaio.command_registry import register
from velbusaio.message_fields import DeclarativeMessage

COMMAND_CODE = 0xE7


@register(COMMAND_CODE)
class TempSensorSettingsRequest(DeclarativeMessage):
    """TempSensorSettingsRequest message class."""

    _command_code = COMMAND_CODE

    def data_to_binary(self):
        """:return: bytes

        The protocol specifies two data bytes for this command, the second one
        a "don't care". A module compares the data length and ignores a frame
        that does not match, so sending only the command byte gets no reply.
        """
        return bytes([COMMAND_CODE, 0x00])
