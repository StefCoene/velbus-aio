"""Schema-driven configuration parameters for Velbus modules/channels."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import KW_ONLY, dataclass, field
from typing import Any, Literal

from velbusaio.exceptions import VelbusConfigError

ConfigKind = Literal["bool", "number", "select", "text"]


@dataclass(slots=True)
class ConfigParameter:
    """A discoverable read/write configuration parameter."""

    key: str
    label: str
    kind: ConfigKind
    getter: Callable[[], Awaitable[Any]]
    setter: Callable[[Any], Awaitable[None]]
    _: KW_ONLY
    options: list[str] | None = None
    min_value: float | None = None
    max_value: float | None = None
    max_length: int | None = None
    channel: int | None = None
    entity_category: str = "config"
    # False = config-panel only; do not expose as a Home Assistant entity.
    entity: bool = True
    # True when writing this changes module eeprom, which is destructive if the
    # addresses are wrong. False when the setter only puts a message on the bus,
    # which a module either accepts or ignores. Callers use this to decide how
    # much ceremony a write needs; the safe default is to assume eeprom.
    writes_memory: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    async def get_value(self) -> Any:
        """Return the current value."""
        return await self.getter()

    async def set_value(self, value: Any) -> None:
        """Write a new value with light validation."""
        if self.kind == "bool":
            value = bool(value)
        elif self.kind == "number":
            value = float(value)
            if self.min_value is not None and value < self.min_value:
                raise VelbusConfigError(f"{self.key} below minimum {self.min_value}")
            if self.max_value is not None and value > self.max_value:
                raise VelbusConfigError(f"{self.key} above maximum {self.max_value}")
        elif self.kind == "select":
            value = str(value)
            if self.options is not None and value not in self.options:
                raise VelbusConfigError(
                    f"{self.key} must be one of {self.options}, got {value!r}"
                )
        elif self.kind == "text":
            value = str(value)
            if self.max_length is not None and len(value) > self.max_length:
                raise VelbusConfigError(
                    f"{self.key} exceeds max length {self.max_length}"
                )
        await self.setter(value)

    def to_dict(self) -> dict[str, Any]:
        """Return metadata for discovery (without live values)."""
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "options": self.options,
            "min": self.min_value,
            "max": self.max_value,
            "max_length": self.max_length,
            "channel": self.channel,
            "entity_category": self.entity_category,
            "entity": self.entity,
            "writes_memory": self.writes_memory,
            "metadata": self.metadata,
        }


def encode_name(name: str, length: int) -> bytes:
    """Encode a channel/module name into fixed-length EEPROM bytes."""
    raw = name.encode("latin-1", errors="replace")[:length]
    return raw + bytes([0xFF] * (length - len(raw)))


def decode_name(data: bytes) -> str:
    """Decode a name from EEPROM bytes (0xFF / 0x00 padded)."""
    chars: list[str] = []
    for value in data:
        if value in (0x00, 0xFF):
            break
        chars.append(chr(value))
    return "".join(chars)
