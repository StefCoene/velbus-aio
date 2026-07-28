"""Velbusaio property classes.

author: Maikel Punie <maikel.punie@gmail.com>
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from velbusaio.autosend import (
    AUTOSEND_HINT,
    AUTOSEND_INTERVAL_MAX,
    AUTOSEND_NO_CHANGE,
    decode_autosend_interval,
    encode_autosend_interval,
)
from velbusaio.baseItem import BaseItem
from velbusaio.command_registry import commandRegistry
from velbusaio.config import ConfigParameter
from velbusaio.exceptions import VelbusConfigError
from velbusaio.message import Message
from velbusaio.messages.module_status import PROGRAM_SELECTION

if TYPE_CHECKING:
    from velbusaio.module import Module


class Property(BaseItem):
    """Base class for module-level properties."""

    def get_channel_number(self) -> int:
        """Return the channel number of this property (always 0)."""
        return 0

    def get_identifier(self) -> str:
        """Return the identifier of the entity."""
        return str(self.get_module_address())

    def is_sub_device(self) -> bool:
        """Return false, a property is never a subdevice."""
        return False

    def get_categories(self) -> list[str]:
        """Get the category of this property.

        default is 'sensor'.
        Override in subclass if needed.
        """
        return ["sensor"]

    def get_sensor_type(self) -> str:
        """Get the sensor type of this property.

        Override in subclass if needed.
        """
        return type(self).__name__

    def get_property_key(self) -> str:
        """Return a stable, type-unique key for use in unique_id generation."""
        return type(self).__name__


class PSUPower(Property):
    """PSU Power property."""

    def __init__(
        self, module: Module, name: str, writer: Callable[[Message], Awaitable[None]]
    ):
        """Initialize PSU power property with per-instance current value."""
        super().__init__(module, name, writer)
        self._cur: float = 0.0

    def get_state(self) -> float:
        """Return the current state of the PSU power."""
        return round(self._cur, 2)


class PSUVoltage(PSUPower):
    """PSU Voltage property."""


class PSUCurrent(PSUPower):
    """PSU Current property."""


class PSULoad(PSUPower):
    """PSU Load property."""


class MemoText(Property):
    """Memo text property."""

    def get_categories(self) -> list[str]:
        """The MemoText property has no categories."""
        return []

    async def set(self, txt: str) -> None:
        """Set the memo text."""
        cls = commandRegistry.get_command(0xAC, self._module.get_type())
        msg = cls(self.get_module_address())
        msgcntr = 0
        for char in txt:
            msg.memo_text += char
            if len(msg.memo_text) >= 5:
                msgcntr += 5
                await self._writer(msg)
                msg = cls(self.get_module_address())
                msg.start = msgcntr
        if msg.memo_text:
            await self._writer(msg)


class SelectedProgram(Property):
    """A selected program property."""

    def __init__(
        self, module: Module, name: str, writer: Callable[[Message], Awaitable[None]]
    ):
        """Initialize Selected Program property with per-instance current value."""
        super().__init__(module, name, writer)
        self._selected_program_str: str | None = None

    def get_categories(self) -> list[str]:
        """Return the categories for this property."""
        return ["select"]

    def get_class(self) -> None:
        """Return the device class for this property."""
        return

    def get_options(self) -> list:
        """Return the available program options for this property."""
        return list(PROGRAM_SELECTION.values())

    def get_selected_program(self) -> str | None:
        """Return the currently selected program."""
        return self._selected_program_str

    async def set_selected_program(self, program_str: str) -> None:
        """Set the currently selected program."""
        command_code = 0xB3
        cls = commandRegistry.get_command(command_code, self._module.get_type())
        index = list(PROGRAM_SELECTION.values()).index(program_str)
        program = list(PROGRAM_SELECTION.keys())[index]
        msg = cls(self.get_module_address(), program)
        await self._writer(msg)
        await self.update({"selected_program_str": program_str})


class LightValue(Property):
    """Light value property."""

    def __init__(
        self, module: Module, name: str, writer: Callable[[Message], Awaitable[None]]
    ):
        """Initialize light value property with per-instance current value."""
        super().__init__(module, name, writer)
        self._cur: float = 0.0
        self._send_interval: int = AUTOSEND_NO_CHANGE

    def get_state(self) -> float:
        """Return the current light sensor value."""
        return round(self._cur, 2)

    def get_autosend_interval(self) -> int:
        """Return the interval byte the module last reported.

        Only the PIR status messages carry it; on a module that reports its
        light value through a plain module status this stays 0 ("unknown").
        """
        return self._send_interval

    def get_autosend(self) -> tuple[str, int | None]:
        """Return the (mode, seconds) the module last reported."""
        return decode_autosend_interval(self._send_interval)

    async def set_autosend(self, mode: str, seconds: int | None = None) -> None:
        """Configure how often the module sends its light value on the bus.

        :param mode: one of ``"never"`` (auto send disabled), ``"on_change"``
            (auto send on every change) or ``"interval"`` (a fixed interval,
            requires ``seconds``).
        :param seconds: the interval in seconds (10..255), only used and
            required when ``mode`` is ``"interval"``.
        """
        await self._write_interval(encode_autosend_interval(mode, seconds))

    def get_config_parameters(self) -> list[ConfigParameter]:
        """Return the auto send interval as a discoverable CONFIG parameter."""
        return [
            ConfigParameter(
                key="light_autosend_interval",
                label="Light value autosend interval",
                kind="number",
                getter=self._get_interval,
                setter=self._set_interval,
                min_value=float(AUTOSEND_NO_CHANGE),
                max_value=float(AUTOSEND_INTERVAL_MAX),
                channel=self.get_channel_number(),
                # Command AA goes on the bus; nothing is written to eeprom.
                writes_memory=False,
                metadata={"unit": "s", "hint": AUTOSEND_HINT},
            )
        ]

    async def _get_interval(self) -> int:
        return self._send_interval

    async def _set_interval(self, value: float) -> None:
        """Write a raw interval byte, the way the temperature settings do."""
        await self._write_interval(int(value))

    async def _write_interval(self, interval: int) -> None:
        cls = commandRegistry.get_command(0xAA, self._module.get_type())
        if cls is None:
            raise VelbusConfigError(
                f"Module type {self._module.get_type():#04x} does not support "
                "setting the light value autosend interval"
            )
        msg = cls(self.get_module_address(), interval)
        await self._writer(msg)
        # The module does not confirm the new setting, it just starts using it.
        await self.update({"send_interval": interval})


class BusErrorTx(Property):
    """Bus Error Transmit property."""

    def __init__(
        self, module: Module, name: str, writer: Callable[[Message], Awaitable[None]]
    ):
        """Initialize Bus Error Transmit property with per-instance current value."""
        super().__init__(module, name, writer)
        self._cur: int = 0

    def get_state(self) -> float:
        """Return the current Bus Error Transmit count."""
        return float(self._cur)


class BusErrorRx(BusErrorTx):
    """Bus Error Receive property."""


class BusErrorOff(BusErrorTx):
    """Bus Error OFF property."""
