"""Test cases for configuring the light value auto send interval."""

from __future__ import annotations

import pytest

from velbusaio.command_registry import commandRegistry
from velbusaio.const import PRIORITY_LOW
from velbusaio.exceptions import VelbusConfigError
from velbusaio.messages.light_value_request import (
    LIGHT_AUTOSEND_DISABLED,
    LIGHT_AUTOSEND_ON_CHANGE,
    LightValueRequest,
)
from velbusaio.messages.module_status import ModuleStatusPirMessage
from velbusaio.properties import LightValue

# 0x2C is the VMBPIRO, one of the 14 module types whose spec maps command AA.
VMBPIRO = 0x2C


@pytest.fixture(name="light")
def light_fixture(mock_module, mock_writer) -> LightValue:
    """Return a light value property on a module that supports command AA."""
    commandRegistry.register_module_commands(VMBPIRO, {"AA": "LightValueRequest"})
    mock_module.get_type.return_value = VMBPIRO
    mock_module.get_addresses.return_value = [VMBPIRO]
    return LightValue(mock_module, "Light", mock_writer)


class TestLightValueRequestMessage:
    """Test cases for the message itself."""

    def test_plain_request_is_one_byte(self) -> None:
        """Without an interval the message stays what it always was."""
        assert LightValueRequest().data_to_binary() == bytes([0xAA])

    @pytest.mark.parametrize(
        ("interval", "expected"),
        [
            (LIGHT_AUTOSEND_DISABLED, 0x01),
            (LIGHT_AUTOSEND_ON_CHANGE, 0x05),
            (60, 60),
            (255, 255),
        ],
    )
    def test_interval_lands_in_databyte2(self, interval: int, expected: int) -> None:
        """The interval is DATABYTE2 of command AA."""
        msg = LightValueRequest(0x10, interval)
        assert msg.data_to_binary() == bytes([0xAA, expected])


class TestSetAutosend:
    """Test cases for LightValue.set_autosend()."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("mode", "seconds", "expected"),
        [("never", None, 0x01), ("on_change", None, 0x05), ("interval", 30, 30)],
    )
    async def test_sends_command_aa(
        self, light: LightValue, mock_writer, mode, seconds, expected
    ) -> None:
        """Each mode puts the right byte on the bus."""
        await light.set_autosend(mode, seconds)

        message = mock_writer.await_args.args[0]
        assert message.data_to_binary() == bytes([0xAA, expected])

    @pytest.mark.asyncio
    async def test_remembers_what_was_set(self, light: LightValue) -> None:
        """The module never confirms, so the setting is kept locally."""
        await light.set_autosend("interval", 45)

        assert light.get_autosend() == ("interval", 45)
        assert light.get_autosend_interval() == 45

    @pytest.mark.asyncio
    async def test_rejects_an_unusable_interval(self, light: LightValue) -> None:
        """Validation happens before anything reaches the bus."""
        with pytest.raises(ValueError, match="must be between 10 and 255"):
            await light.set_autosend("interval", 3)

    @pytest.mark.asyncio
    async def test_module_without_command_aa(self, mock_module, mock_writer) -> None:
        """A module type that cannot do this says so instead of crashing."""
        mock_module.get_type.return_value = 0x01
        light = LightValue(mock_module, "Light", mock_writer)

        with pytest.raises(VelbusConfigError, match="does not support"):
            await light.set_autosend("never")


class TestReportedInterval:
    """Test cases for the interval a module reports in its status message."""

    def test_pir_status_carries_databyte8(self) -> None:
        """DATABYTE8 of the PIR module status is the light autosend interval."""
        msg = ModuleStatusPirMessage()
        msg.populate(
            PRIORITY_LOW, 0x01, False, bytes([0x03, 0x01, 0x02, 0, 0, 0x01, 30])
        )

        assert msg.light_value == (0x01 << 8) + 0x02
        assert msg.light_value_send_interval == 30

    @pytest.mark.asyncio
    async def test_unknown_until_a_module_reports(self, light: LightValue) -> None:
        """0 means the module never told us, which is not a mode."""
        assert light.get_autosend() == ("unknown", None)

    @pytest.mark.asyncio
    async def test_update_feeds_the_property(self, light: LightValue) -> None:
        """The handler passes the reported byte through update()."""
        await light.update({"cur": 120, "send_interval": 15})

        assert light.get_state() == 120
        assert light.get_autosend() == ("interval", 15)


class TestConfigParameter:
    """Test cases for the discoverable CONFIG parameter."""

    def test_exposes_one_number(self, light: LightValue) -> None:
        """It mirrors the temperature autosend parameter."""
        (param,) = light.get_config_parameters()

        assert param.key == "light_autosend_interval"
        assert param.kind == "number"
        assert (param.min_value, param.max_value) == (0.0, 255.0)

    @pytest.mark.asyncio
    async def test_writes_a_raw_byte(self, light: LightValue, mock_writer) -> None:
        """Setting it puts the byte on the bus unchanged."""
        (param,) = light.get_config_parameters()
        await param.set_value(90)

        assert mock_writer.await_args.args[0].data_to_binary() == bytes([0xAA, 90])
        assert await param.get_value() == 90

    @pytest.mark.asyncio
    async def test_rejects_a_byte_that_does_not_fit(self, light: LightValue) -> None:
        """ConfigParameter enforces the range before the setter runs."""
        (param,) = light.get_config_parameters()

        with pytest.raises(VelbusConfigError, match="above maximum"):
            await param.set_value(300)
