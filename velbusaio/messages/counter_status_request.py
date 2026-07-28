"""Counter Status Request message.

:author: Maikel Punie <maikel.punie@gmail.com>
"""

from __future__ import annotations

from velbusaio.autosend import AUTOSEND_NO_CHANGE
from velbusaio.command_registry import register
from velbusaio.message import Message
from velbusaio.message_fields import DeclarativeMessage

COMMAND_CODE = 0xBD


@register(COMMAND_CODE)
class CounterStatusRequestMessage(DeclarativeMessage):
    """Counter Status Request message."""

    _command_code = COMMAND_CODE
    _data_length = 2

    wait_after_send = 500

    def __init__(self, address=None, autosend_interval=AUTOSEND_NO_CHANGE):
        """Initialize Counter Status Request message.

        DATABYTE3 configures how often the module puts its counters on the
        bus, in the same encoding the temperature and light requests use. The
        interval is common to every counter channel, so the channel mask in
        DATABYTE2 selects what to report now, not what to configure.
        """
        Message.__init__(self)
        self.channels = []
        self.autosend_interval = autosend_interval
        self.set_defaults(address)

    def data_to_binary(self):
        """:return: bytes"""
        return bytes(
            [
                COMMAND_CODE,
                self.channels_to_byte(self.channels),
                self.autosend_interval & 0xFF,
            ]
        )
