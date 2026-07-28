"""Test cases for auto send intervals that live in module memory."""

from __future__ import annotations

import json
import pathlib
from unittest.mock import AsyncMock, Mock

import pytest

from velbusaio.module import Module

SPEC_DIR = pathlib.Path(__file__).parent.parent / "velbusaio" / "module_spec"

# The module types whose protocol documents H'00F3' and H'00F4' as the eeprom
# locations of the auto send intervals.
PIR_SPECS = ("23", "2A", "2B", "2C")


@pytest.fixture(name="module")
def module_fixture() -> Module:
    """Return a VMBPIRO with a stubbed memory backend."""
    module = Module(83, 0x2C)
    module._data = {
        "TemperatureChannel": "09",
        "Memory": {"AutosendInterval": {"temperature": "00F3", "light": "00F4"}},
    }
    module._memory = Mock()
    module._memory.read_byte = AsyncMock(return_value=60)
    module._memory.get_cached.return_value = None
    return module


class TestDeclaredAddresses:
    """Test cases for the addresses declared in the specs."""

    @pytest.mark.parametrize("name", PIR_SPECS)
    def test_spec_declares_both_addresses(self, name: str) -> None:
        """Both intervals are documented at the same place for every PIR."""
        spec = json.loads((SPEC_DIR / f"{name}.json").read_text())

        assert spec["Memory"]["AutosendInterval"] == {
            "temperature": "00F3",
            "light": "00F4",
        }

    def test_address_is_read_from_the_spec(self, module: Module) -> None:
        """The address is per module type, so it must not be hardcoded."""
        assert module.get_autosend_address("temperature") == 0x00F3
        assert module.get_autosend_address("light") == 0x00F4

    def test_module_without_declared_addresses(self) -> None:
        """Most modules declare none, and that is not an error."""
        other = Module(1, 0x10)
        other._data = {"Memory": {"ModuleName": "00E3-00EF"}}

        assert other.get_autosend_address("temperature") is None


class TestRefresh:
    """Test cases for refresh_autosend_intervals()."""

    @pytest.mark.asyncio
    async def test_reads_both_addresses(self, module: Module) -> None:
        """One read each, at the addresses the spec declares."""
        await module.refresh_autosend_intervals()

        read = [call.args[0] for call in module._memory.read_byte.await_args_list]
        assert read == [0x00F3, 0x00F4]

    @pytest.mark.asyncio
    async def test_a_silent_module_is_not_an_error(self, module: Module) -> None:
        """A module that does not answer leaves the interval unknown."""
        module._memory.read_byte = AsyncMock(side_effect=OSError)

        await module.refresh_autosend_intervals()

        assert module.get_temp_autosend_interval() is None

    @pytest.mark.asyncio
    async def test_without_a_memory_backend(self) -> None:
        """A module restored from cache has no backend to read from."""
        module = Module(83, 0x2C)
        module._data = {"Memory": {"AutosendInterval": {"temperature": "00F3"}}}

        await module.refresh_autosend_intervals()


class TestTempAutosendInterval:
    """Test cases for get_temp_autosend_interval()."""

    def test_falls_back_to_memory(self, module: Module) -> None:
        """The VMBPIRO answers no settings request, so eeprom is the source."""
        module._memory.get_cached.return_value = 60

        assert module.get_temp_autosend_interval() == 60

    def test_settings_win_when_loaded(self, module: Module) -> None:
        """A module that reports Part2 is the more direct source."""
        settings = Mock()
        settings.is_loaded.return_value = True
        settings.get.return_value = 30
        module._temp_settings = settings
        module._memory.get_cached.return_value = 60

        assert module.get_temp_autosend_interval() == 30

    def test_unloaded_settings_do_not_mask_memory(self, module: Module) -> None:
        """Settings that never arrived must not hide the eeprom value."""
        settings = Mock()
        settings.is_loaded.return_value = False
        module._temp_settings = settings
        module._memory.get_cached.return_value = 60

        assert module.get_temp_autosend_interval() == 60

    def test_nothing_known(self, module: Module) -> None:
        """Unknown is None, which is not the same as an interval of zero."""
        assert module.get_temp_autosend_interval() is None

    def test_module_without_a_temperature_sensor(self, module: Module) -> None:
        """A VMBPIRM reserves the byte but never writes it, so it reads 0xFF.

        Reporting that as an interval of 255 seconds would advertise a setting
        for a sensor the module does not have.
        """
        del module._data["TemperatureChannel"]
        module._memory.get_cached.return_value = 0xFF

        assert module.get_temp_autosend_interval() is None
