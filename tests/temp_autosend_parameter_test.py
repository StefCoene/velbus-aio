"""Test cases for setting the temperature auto send interval on a channel."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from velbusaio.channels import Temperature
from velbusaio.command_registry import commandRegistry
from velbusaio.exceptions import VelbusConfigError

# 0x2C is the VMBPIRO: it maps command E5 but never sends settings Part2.
VMBPIRO = 0x2C


@pytest.fixture(name="channel")
def channel_fixture(mock_writer) -> Temperature:
    """Return the temperature channel of a module that has no Part2."""
    commandRegistry.register_module_commands(VMBPIRO, {"E5": "SensorTempRequest"})
    module = Mock()
    module.get_type.return_value = VMBPIRO
    module.get_temp_settings.return_value = None
    module.get_temp_autosend_interval.return_value = 60
    module.refresh_autosend_intervals = AsyncMock()
    return Temperature(module, 9, "Temperature", False, True, mock_writer, 83)


class TestParameter:
    """Test cases for the parameter a module without Part2 still gets."""

    def test_offered_when_settings_cannot_provide_it(
        self, channel: Temperature
    ) -> None:
        """Without Part2 the interval is not among the settings parameters."""
        keys = [param.key for param in channel.get_config_parameters()]

        assert keys == ["autosend_interval"]

    def test_not_duplicated_when_settings_provide_it(
        self, channel: Temperature
    ) -> None:
        """A module that does send Part2 must not end up with two of them."""
        settings = Mock()
        existing = Mock()
        existing.key = "autosend_interval"
        settings.get_config_parameters.return_value = [existing]
        channel._module.get_temp_settings.return_value = settings

        params = channel.get_config_parameters()

        assert [param.key for param in params] == ["autosend_interval"]
        assert params[0] is existing

    def test_is_not_a_memory_write(self, channel: Temperature) -> None:
        """Command E5 goes on the bus, so it needs no advanced mode."""
        (param,) = channel.get_config_parameters()

        assert param.writes_memory is False


class TestReadWrite:
    """Test cases for reading and writing through the parameter."""

    @pytest.mark.asyncio
    async def test_reads_what_the_module_holds(self, channel: Temperature) -> None:
        """The value comes from wherever the module could get it."""
        (param,) = channel.get_config_parameters()

        assert await param.get_value() == 60

    @pytest.mark.asyncio
    async def test_writes_command_e5(self, channel: Temperature, mock_writer) -> None:
        """The interval is sent as DATABYTE2 of command E5."""
        (param,) = channel.get_config_parameters()

        await param.set_value(30)

        assert mock_writer.await_args.args[0].data_to_binary() == bytes([0xE5, 30])

    @pytest.mark.asyncio
    async def test_reads_back_after_writing(self, channel: Temperature) -> None:
        """The module confirms nothing, so the value is fetched again."""
        (param,) = channel.get_config_parameters()

        await param.set_value(30)

        channel._module.refresh_autosend_intervals.assert_awaited_once_with(
            use_cache=False
        )

    @pytest.mark.asyncio
    async def test_rejects_a_value_that_does_not_fit(
        self, channel: Temperature
    ) -> None:
        """The byte holds 0..255 and the range is enforced before sending."""
        (param,) = channel.get_config_parameters()

        with pytest.raises(VelbusConfigError, match="above maximum"):
            await param.set_value(300)

    @pytest.mark.asyncio
    async def test_module_without_command_e5(
        self, channel: Temperature, mock_writer
    ) -> None:
        """A VMBPIRM maps no E5 and cannot be told this at all."""
        channel._module.get_type.return_value = 0x2A
        (param,) = channel.get_config_parameters()

        with pytest.raises(VelbusConfigError, match="does not support"):
            await param.set_value(30)
        mock_writer.assert_not_awaited()
