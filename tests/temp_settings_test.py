"""Tests for temperature sensor settings over the bus."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from velbusaio.exceptions import VelbusConfigError, VelbusMemoryTimeout
from velbusaio.messages.temp_sensor_settings_part1 import TempSensorSettingsPart1
from velbusaio.messages.temp_sensor_settings_part2 import TempSensorSettingsPart2
from velbusaio.messages.temp_sensor_settings_part3 import TempSensorSettingsPart3
from velbusaio.messages.temp_sensor_settings_part4 import TempSensorSettingsPart4
from velbusaio.messages.temp_sensor_settings_request import TempSensorSettingsRequest
from velbusaio.temp_settings import (
    TemperatureSettings,
    build_temperature_settings,
    infer_temp_settings_layout,
    module_supports_temp_settings,
)


class TestModuleSupport:
    """Module capability helpers."""

    def test_supports_vmb1ts(self):
        """VMB1TS advertises full settings."""
        data = {
            "Type": "VMB1TS",
            "TemperatureChannel": "01",
            "CommandToClass": {
                "E7": "TempSensorSettingsRequest",
                "E8": "TempSensorSettingsPart1",
                "E9": "TempSensorSettingsPart2",
                "C6": "TempSensorSettingsPart3",
                "B9": "TempSensorSettingsPart4",
            },
        }
        assert module_supports_temp_settings(data)
        assert infer_temp_settings_layout(data) == "classic"
        settings = build_temperature_settings(0x0C, AsyncMock(), data, channel=1)
        assert settings is not None
        assert settings.layout == "classic"
        assert settings.has_part4

    def test_rejects_dali_command_overlap(self):
        """DALI also uses 0xE7/0xE8 but is not a temp sensor."""
        data = {
            "Type": "VMBDALI",
            "CommandToClass": {
                "E7": "TempSensorSettingsRequest",
                "E8": "TempSensorSettingsPart1",
            },
        }
        assert not module_supports_temp_settings(data)
        assert build_temperature_settings(0x45, AsyncMock(), data) is None

    def test_gp_layout(self):
        """Glass panels use the GP Part3/4 layout."""
        assert (
            infer_temp_settings_layout({"Type": "VMBGP4", "TempSettingsLayout": "gp"})
            == "gp"
        )


class TestTemperatureSettings:
    """TemperatureSettings refresh / write behaviour."""

    @pytest.mark.asyncio
    async def test_refresh_and_set_comfort(self):
        """Request settings, feed replies, then write one field."""
        written: list = []
        settings_box: list[TemperatureSettings] = []

        async def writer(msg):
            written.append(msg)
            settings = settings_box[0]
            if isinstance(msg, TempSensorSettingsRequest):
                part1 = TempSensorSettingsPart1(0x0C)
                part1.current_set = 20
                part1.comfort_heating = 21
                part1.day_heating = 20
                part1.night_heating = 18
                part1.antifreeze_heating = 5
                part1.temp_difference = 2
                part1.hysteresis = 0.5
                settings.feed_message(part1)

                part2 = TempSensorSettingsPart2(0x0C)
                part2.comfort_cooling = 24
                part2.day_cooling = 23
                part2.night_cooling = 22
                part2.safe_cooling = 21
                part2.default_sleep_timer = 60
                part2.autosend_interval = 30
                settings.feed_message(part2)

                part3 = TempSensorSettingsPart3(0x0C, layout="classic")
                part3.alarm_low = 5
                part3.alarm_high = 30
                part3.cool_lower = 8
                part3.heat_upper = 25
                part3.calibration = 0
                part3.slave_or_zone = 0xFF
                settings.feed_message(part3)

                part4 = TempSensorSettingsPart4(0x0C, layout="classic")
                part4.min_switching_time = 1
                settings.feed_message(part4)

        settings = TemperatureSettings(
            0x0C,
            writer,
            layout="classic",
            channel=1,
            timeout=1.0,
        )
        settings_box.append(settings)
        values = await settings.refresh()
        assert values["comfort_heating"] == 21.0
        assert values["default_sleep_timer"] == 60
        assert values["min_switching_time"] == 1

        await settings.set_value("comfort_heating", 22.5)
        assert isinstance(written[-1], TempSensorSettingsPart1)
        assert written[-1].comfort_heating == 22.5
        assert written[-1].data_to_binary()[2] == 45  # 22.5 * 2

        params = settings.get_config_parameters()
        keys = {param.key for param in params}
        assert keys == {
            "temp_difference",
            "hysteresis",
            "default_sleep_timer",
            "autosend_interval",
        }

        param = next(p for p in params if p.key == "hysteresis")
        assert await param.get_value() == 0.5
        await param.set_value(1.0)
        assert settings.get("hysteresis") == 1.0

    @pytest.mark.asyncio
    async def test_refresh_timeout(self):
        """Missing replies raise VelbusMemoryTimeout."""
        settings = TemperatureSettings(
            0x0C,
            AsyncMock(),
            layout="classic",
            timeout=0.05,
        )
        with pytest.raises(VelbusMemoryTimeout):
            await settings.refresh()

    @pytest.mark.asyncio
    async def test_unknown_key(self):
        """Unknown setting keys are rejected."""
        settings = TemperatureSettings(0x0C, AsyncMock(), layout="classic")
        settings._loaded_parts = {1, 2, 3, 4}
        with pytest.raises(VelbusConfigError):
            await settings.set_value("nope", 1)
