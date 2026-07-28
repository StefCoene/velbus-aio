"""Test cases for collecting a module's configuration parameters."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from velbusaio.config import ConfigParameter
from velbusaio.module import Module
from velbusaio.panel_schema import _config_entries


def _param(key: str, *, channel: int | None, writes_memory: bool) -> ConfigParameter:
    return ConfigParameter(
        key=key,
        label=key,
        kind="number",
        getter=AsyncMock(return_value=60),
        setter=AsyncMock(),
        channel=channel,
        writes_memory=writes_memory,
    )


@pytest.fixture(name="module")
def module_fixture() -> Module:
    """Return a module with two channels and one property carrying parameters."""
    module = Module(0x20, 0x20)
    channel = Mock()
    channel.get_config_parameters.return_value = [
        _param("name", channel=1, writes_memory=True),
        _param("autosend_interval", channel=1, writes_memory=False),
    ]
    plain = Mock(spec=[])  # a channel without configuration parameters
    prop = Mock()
    prop.get_config_parameters.return_value = [
        _param("light_autosend_interval", channel=0, writes_memory=False)
    ]
    module._channels = {1: channel, 2: plain}
    module._properties = {"light_value": prop}
    return module


class TestGetConfigParameters:
    """Test cases for Module.get_config_parameters()."""

    def test_collects_from_channels_and_properties(self, module: Module) -> None:
        """A caller should not have to know where a setting lives."""
        keys = [param.key for param in module.get_config_parameters()]

        assert keys == ["name", "autosend_interval", "light_autosend_interval"]

    def test_skips_items_without_parameters(self, module: Module) -> None:
        """Most channels have none, and that is not an error."""
        assert len(module.get_config_parameters()) == 3


class TestFindConfigParameter:
    """Test cases for Module.find_config_parameter()."""

    def test_finds_by_key(self, module: Module) -> None:
        """A module level parameter has no channel to narrow it down."""
        param = module.find_config_parameter("light_autosend_interval")

        assert param is not None
        assert param.channel == 0

    def test_channel_narrows_the_match(self, module: Module) -> None:
        """The same key can exist on several channels."""
        assert module.find_config_parameter("name", 1) is not None
        assert module.find_config_parameter("name", 2) is None

    def test_unknown_key(self, module: Module) -> None:
        """An unknown key is None rather than an exception."""
        assert module.find_config_parameter("nope") is None


class TestConfigEntries:
    """Test cases for the panel's config section."""

    @pytest.mark.asyncio
    async def test_only_lists_settings_that_do_not_write_memory(
        self, module: Module
    ) -> None:
        """The name, enabled and contact already have their own sections."""
        entries = await _config_entries(module)

        assert [entry["key"] for entry in entries] == [
            "autosend_interval",
            "light_autosend_interval",
        ]

    @pytest.mark.asyncio
    async def test_includes_the_live_value(self, module: Module) -> None:
        """The panel needs to show what the module is set to now."""
        entries = await _config_entries(module)

        assert all(entry["value"] == 60 for entry in entries)

    @pytest.mark.asyncio
    async def test_a_failed_read_does_not_sink_the_page(self, module: Module) -> None:
        """A module that does not answer leaves one value unknown, not all."""
        params = module.get_config_parameters()
        params[1].getter = AsyncMock(side_effect=TimeoutError)
        module._channels[1].get_config_parameters.return_value = params[:2]

        entries = await _config_entries(module)

        assert entries[0]["key"] == "autosend_interval"
        assert entries[0]["value"] is None
        assert entries[1]["value"] == 60
