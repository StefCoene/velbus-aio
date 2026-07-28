"""Temperature sensor settings over the Velbus (TempSensorSettings Part1-4)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import KW_ONLY, dataclass, field
import logging
from typing import Any, Final

from velbusaio.autosend import AUTOSEND_HINT
from velbusaio.config import ConfigParameter
from velbusaio.exceptions import VelbusConfigError, VelbusMemoryTimeout
from velbusaio.message import Message
from velbusaio.messages.temp_sensor_settings_part1 import TempSensorSettingsPart1
from velbusaio.messages.temp_sensor_settings_part2 import TempSensorSettingsPart2
from velbusaio.messages.temp_sensor_settings_part3 import TempSensorSettingsPart3
from velbusaio.messages.temp_sensor_settings_part4 import TempSensorSettingsPart4
from velbusaio.messages.temp_sensor_settings_request import TempSensorSettingsRequest

_DEFAULT_TIMEOUT: Final = 2.0

# Fields that map onto Part1 / Part2 frames (identical across module layouts).
_PART1_FIELDS: Final = (
    "current_set",
    "comfort_heating",
    "day_heating",
    "night_heating",
    "antifreeze_heating",
    "temp_difference",
    "hysteresis",
)
_PART2_FIELDS: Final = (
    "comfort_cooling",
    "day_cooling",
    "night_cooling",
    "safe_cooling",
    "default_sleep_timer",
    "autosend_interval",
)
_PART3_FIELDS: Final = (
    "alarm_low",
    "alarm_high",
    "cool_lower",
    "heat_upper",
    "calibration",
    "slave_or_zone",
    "calibration_gain",
)
_PART4_FIELDS: Final = (
    "min_switching_time",
    "pump_delayed_on",
    "pump_delayed_off",
    "alarm_2",
    "alarm_3",
    "heat_lower",
    "cool_upper",
)

_FIELD_PART: Final[dict[str, int]] = {
    **dict.fromkeys(_PART1_FIELDS, 1),
    **dict.fromkeys(_PART2_FIELDS, 2),
    **dict.fromkeys(_PART3_FIELDS, 3),
    **dict.fromkeys(_PART4_FIELDS, 4),
}

# Settings that steer a thermostat rather than describe the sensor.
_THERMOSTAT_ONLY: Final = frozenset(
    {"temp_difference", "hysteresis", "default_sleep_timer"}
)

# CONFIG numbers for HA: thermostat presets are already on the climate entity.
_CONFIG_NUMBER_SPECS: Final[tuple[tuple[str, str, float, float], ...]] = (
    ("temp_difference", "Boost difference", -10.0, 10.0),
    ("hysteresis", "Hysteresis", 0.0, 15.5),
    ("default_sleep_timer", "Default sleep", 1.0, 65279.0),
    ("autosend_interval", "Temperature autosend interval", 0.0, 255.0),
)


@dataclass(slots=True)
class TemperatureSettings:
    """Cached temperature sensor settings with request / write helpers."""

    module_address: int
    writer: Callable[[Message], Awaitable[None]]
    _: KW_ONLY
    layout: str = "gp"
    has_part2: bool = True
    has_part3: bool = True
    has_part4: bool = True
    has_thermostat: bool = True
    channel: int | None = None
    logger: logging.Logger | None = None
    timeout: float = _DEFAULT_TIMEOUT
    _values: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _loaded_parts: set[int] = field(default_factory=set, init=False, repr=False)
    _waiters: dict[int, asyncio.Future[None]] = field(
        default_factory=dict, init=False, repr=False
    )
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    @property
    def _log(self) -> logging.Logger:
        return self.logger or logging.getLogger("velbus-temp-settings")

    @property
    def values(self) -> dict[str, Any]:
        """Return a copy of the cached settings."""
        return dict(self._values)

    def is_loaded(self) -> bool:
        """Return True when all expected settings parts have been received."""
        expected = {1}
        if self.has_part2:
            expected.add(2)
        if self.has_part3:
            expected.add(3)
        if self.has_part4:
            expected.add(4)
        return expected <= self._loaded_parts

    def feed_message(self, message: Message) -> None:
        """Update the cache from a settings Part1-4 reply."""
        if isinstance(message, TempSensorSettingsPart1):
            self._apply_part(
                1,
                {
                    "current_set": message.current_set,
                    "comfort_heating": message.comfort_heating,
                    "day_heating": message.day_heating,
                    "night_heating": message.night_heating,
                    "antifreeze_heating": message.antifreeze_heating,
                    "temp_difference": message.temp_difference,
                    "hysteresis": message.hysteresis,
                },
            )
        elif isinstance(message, TempSensorSettingsPart2):
            self._apply_part(
                2,
                {
                    "comfort_cooling": message.comfort_cooling,
                    "day_cooling": message.day_cooling,
                    "night_cooling": message.night_cooling,
                    "safe_cooling": message.safe_cooling,
                    "default_sleep_timer": message.default_sleep_timer,
                    "autosend_interval": message.autosend_interval,
                },
            )
        elif isinstance(message, TempSensorSettingsPart3):
            self._apply_part(
                3,
                {
                    "alarm_low": message.alarm_low,
                    "alarm_high": message.alarm_high,
                    "cool_lower": message.cool_lower,
                    "heat_upper": message.heat_upper,
                    "calibration": message.calibration,
                    "slave_or_zone": message.slave_or_zone,
                    "calibration_gain": message.calibration_gain,
                },
            )
        elif isinstance(message, TempSensorSettingsPart4):
            self._apply_part(
                4,
                {
                    "min_switching_time": message.min_switching_time,
                    "pump_delayed_on": message.pump_delayed_on,
                    "pump_delayed_off": message.pump_delayed_off,
                    "alarm_2": message.alarm_2,
                    "alarm_3": message.alarm_3,
                    "heat_lower": message.heat_lower,
                    "cool_upper": message.cool_upper,
                },
            )

    def _apply_part(self, part: int, values: dict[str, Any]) -> None:
        self._values.update(values)
        self._loaded_parts.add(part)
        waiter = self._waiters.pop(part, None)
        if waiter is not None and not waiter.done():
            waiter.set_result(None)

    def get(self, key: str, default: Any = None) -> Any:
        """Return one cached value."""
        return self._values.get(key, default)

    async def refresh(self, *, force: bool = True) -> dict[str, Any]:
        """Request settings from the module and wait for replies."""
        async with self._lock:
            if not force and self.is_loaded():
                return self.values
            expected = [1]
            if self.has_part2:
                expected.append(2)
            if self.has_part3:
                expected.append(3)
            if self.has_part4:
                expected.append(4)
            waiters: dict[int, asyncio.Future[None]] = {}
            loop = asyncio.get_running_loop()
            for part in expected:
                if part in self._waiters and not self._waiters[part].done():
                    waiters[part] = self._waiters[part]
                else:
                    fut: asyncio.Future[None] = loop.create_future()
                    self._waiters[part] = fut
                    waiters[part] = fut
            self._loaded_parts.clear()
            await self.writer(TempSensorSettingsRequest(self.module_address))
            try:
                await asyncio.wait_for(
                    asyncio.gather(*waiters.values()),
                    timeout=self.timeout,
                )
            except TimeoutError as err:
                missing = [p for p, fut in waiters.items() if not fut.done()]
                raise VelbusMemoryTimeout(
                    self.module_address,
                    operation=f"temp settings parts {missing}",
                ) from err
            finally:
                for part, fut in waiters.items():
                    if self._waiters.get(part) is fut:
                        self._waiters.pop(part, None)
            return self.values

    async def ensure_loaded(self) -> None:
        """Load settings once if not already complete.

        Not forced: several callers can ask at the same moment, all see an
        empty cache, and all queue on the lock. Forcing would make each of
        them wipe what the previous one just loaded and request it again,
        replacing the futures the earlier request was still waiting on.
        """
        if not self.is_loaded():
            await self.refresh(force=False)

    async def set_value(self, key: str, value: Any) -> None:
        """Update one setting and write the owning Part frame to the bus."""
        if key not in _FIELD_PART:
            raise VelbusConfigError(f"Unknown temperature setting: {key!r}")
        part = _FIELD_PART[key]
        if part == 2 and not self.has_part2:
            raise VelbusConfigError(f"{key} requires settings Part2")
        if part == 3 and not self.has_part3:
            raise VelbusConfigError(f"{key} requires settings Part3")
        if part == 4 and not self.has_part4:
            raise VelbusConfigError(f"{key} requires settings Part4")
        await self.ensure_loaded()
        if key in (
            "default_sleep_timer",
            "autosend_interval",
            "slave_or_zone",
            "calibration_gain",
            "min_switching_time",
            "pump_delayed_on",
            "pump_delayed_off",
        ):
            value = int(value)
        else:
            value = float(value)
        self._values[key] = value
        await self._write_part(part)

    async def _write_part(self, part: int) -> None:
        if part == 1:
            msg = TempSensorSettingsPart1(self.module_address)
            for name in _PART1_FIELDS:
                setattr(msg, name, self._values.get(name, 0))
        elif part == 2:
            msg = TempSensorSettingsPart2(self.module_address)
            for name in _PART2_FIELDS:
                setattr(msg, name, self._values.get(name, 0))
        elif part == 3:
            msg = TempSensorSettingsPart3(self.module_address, layout=self.layout)
            for name in _PART3_FIELDS:
                setattr(
                    msg,
                    name,
                    self._values.get(name, 0 if name != "slave_or_zone" else 0xFF),
                )
        elif part == 4:
            msg = TempSensorSettingsPart4(self.module_address, layout=self.layout)
            for name in _PART4_FIELDS:
                setattr(msg, name, self._values.get(name, 0))
        else:
            raise VelbusConfigError(f"Unknown settings part: {part}")
        await self.writer(msg)

    def get_config_parameters(self) -> list[ConfigParameter]:
        """Return discoverable CONFIG number parameters for Part1/Part2."""
        params: list[ConfigParameter] = []
        for key, label, min_value, max_value in _CONFIG_NUMBER_SPECS:
            part = _FIELD_PART[key]
            if part == 2 and not self.has_part2:
                continue
            if key in _THERMOSTAT_ONLY and not self.has_thermostat:
                continue
            params.append(
                ConfigParameter(
                    key=key,
                    label=label,
                    kind="number",
                    getter=self._make_getter(key),
                    setter=self._make_setter(key),
                    min_value=min_value,
                    max_value=max_value,
                    channel=self.channel,
                    # Settings go out as a Part1-4 message, not an eeprom write.
                    writes_memory=False,
                    metadata={
                        "unit": (
                            "min"
                            if key == "default_sleep_timer"
                            else "s"
                            if key == "autosend_interval"
                            else "°C"
                        ),
                        **(
                            {"hint": AUTOSEND_HINT}
                            if key == "autosend_interval"
                            else {}
                        ),
                    },
                )
            )
        return params

    def _make_getter(self, key: str) -> Callable[[], Awaitable[Any]]:
        async def getter() -> Any:
            await self.ensure_loaded()
            return self._values.get(key)

        return getter

    def _make_setter(self, key: str) -> Callable[[Any], Awaitable[None]]:
        async def setter(value: Any) -> None:
            await self.set_value(key, value)

        return setter


def module_has_thermostat(module_data: dict[str, Any]) -> bool:
    """Return True when the module can regulate temperature, not just measure it.

    A VMBPIRO carries a temperature sensor but no thermostat, so the settings
    that steer one -- the boost difference, the hysteresis, the sleep timer --
    mean nothing on it.
    """
    return any(
        channel.get("Type") == "ThermostatChannel"
        for channel in (module_data.get("Channels") or {}).values()
    )


def module_supports_temp_settings(module_data: dict[str, Any]) -> bool:
    """Return True when the module advertises temperature settings commands."""
    cmds = module_data.get("CommandToClass", {})
    return (
        cmds.get("E7") == "TempSensorSettingsRequest"
        and cmds.get("E8") == "TempSensorSettingsPart1"
        and "TemperatureChannel" in module_data
    )


def infer_temp_settings_layout(module_data: dict[str, Any]) -> str:
    """Infer classic vs GP settings layout from the module type."""
    explicit = module_data.get("TempSettingsLayout")
    if explicit in ("classic", "gp"):
        return explicit
    module_type = str(module_data.get("Type", "")).upper()
    if module_type in {"VMB1TS", "VMB1TC", "VMB1TCW"}:
        return "classic"
    return "gp"


def build_temperature_settings(
    module_address: int,
    writer: Callable[[Message], Awaitable[None]],
    module_data: dict[str, Any],
    *,
    channel: int | None = None,
    logger: logging.Logger | None = None,
) -> TemperatureSettings | None:
    """Build a TemperatureSettings helper when the module supports it."""
    if not module_supports_temp_settings(module_data):
        return None
    cmds = module_data.get("CommandToClass", {})
    return TemperatureSettings(
        module_address,
        writer,
        layout=infer_temp_settings_layout(module_data),
        has_part2=cmds.get("E9") == "TempSensorSettingsPart2",
        has_part3=cmds.get("C6") == "TempSensorSettingsPart3",
        has_part4=cmds.get("B9") == "TempSensorSettingsPart4",
        has_thermostat=module_has_thermostat(module_data),
        channel=channel,
        logger=logger,
    )
