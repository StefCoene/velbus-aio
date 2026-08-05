"""Read every action table of an installation and keep the result on disk.

Reading an action table is the slowest thing this library does: the tables live
in module eeprom, which is only reachable four bytes at a time, and a whole
installation runs to a few thousand of those reads. That is minutes of bus
traffic for data that changes only when somebody programs the bus, so it is
worth keeping.

What gets stored is the raw eeprom bytes, not the parsed slots. The parsing
rules live in ``actions.py`` and change with the library; the bytes are what the
module actually holds. Restoring them into ``MemoryBackend`` means a later
``ActionTable.load()`` is served from memory and every consumer keeps using the
same code path, whether the bytes came from the bus or from disk.

The cache cannot notice somebody programming the same module with VelbusLink.
Every entry therefore records when it was read and against which module, and
callers are expected to offer a refresh rather than to trust it forever.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
import json
import logging
import os
import pathlib
import time
from typing import TYPE_CHECKING, Any, Final

import anyio

from velbusaio.actions import ActionSlot, ActionTable

if TYPE_CHECKING:
    from velbusaio.controller import Velbus
    from velbusaio.module import Module

_LOGGER: Final = logging.getLogger("velbus-action-cache")

CACHE_VERSION: Final = 1
CACHE_SUFFIX: Final = "-actions.json"

type ProgressCallback = Callable[["ScanProgress"], None]
type BytesCallback = Callable[[int, int], None]


@dataclass(slots=True)
class ScanProgress:
    """How far a scan has come, reported as it reads.

    Modules are the coarse unit and bytes the fine one. Reading a single module
    is one module either way, so the byte counters are what says anything is
    happening -- and they are the honest unit anyway, because a shared table is
    read once for every channel that points at it.
    """

    done: int
    total: int
    address: int
    name: str
    bytes_done: int = 0
    bytes_total: int = 0


@dataclass(slots=True)
class ModuleActions:
    """The action tables of one module, per channel."""

    address: int
    name: str
    type_name: str
    channels: dict[int, list[ActionSlot]] = field(default_factory=dict)
    read_at: float = 0.0
    from_cache: bool = False
    error: str | None = None

    @property
    def action_count(self) -> int:
        """Number of programmed slots across all channels."""
        return sum(len(slots) for slots in self.channels.values())


@dataclass(slots=True)
class ActionScan:
    """The result of scanning one or more modules."""

    modules: dict[int, ModuleActions] = field(default_factory=dict)
    duration: float = 0.0

    @property
    def action_count(self) -> int:
        """Number of programmed slots in the whole scan."""
        return sum(module.action_count for module in self.modules.values())

    @property
    def errors(self) -> dict[int, str]:
        """Modules that could not be read, by address."""
        return {
            address: module.error
            for address, module in self.modules.items()
            if module.error is not None
        }


def action_ranges(module: Module) -> list[tuple[int, int]]:
    """Return the eeprom ranges holding this module's action tables.

    A shared table is one range that every channel points at, so the ranges are
    de-duplicated: reading it once per channel would multiply the slowest part
    of a scan by the channel count.
    """
    ranges: set[tuple[int, int]] = set()
    for table in module.get_action_tables().values():
        ranges.add((table.bank, table.slot_count * table.slot_size))
        if table.noc_address is not None:
            ranges.add((table.noc_address, 1))
    return sorted(ranges)


def module_fingerprint(module: Module) -> dict[str, Any]:
    """Identify the module a cache entry was read from.

    A module swapped for another one at the same address has different tables,
    and a firmware upgrade can move them. Neither is common, and neither is
    something the cache should quietly serve stale bytes through.
    """
    return {
        "type": module.get_type(),
        "serial": module.get_serial(),
        "build": module.get_sw_version(),
        "memory_map": module.get_memory_map_build(),
    }


def export_module_actions(module: Module) -> dict[str, Any] | None:
    """Return the cacheable state of a module, or None when it has nothing.

    A range is only written out when every byte of it is known. A partially
    read table would come back looking complete, and the missing bytes read as
    0x00, which ``ActionSlot`` cannot tell from an unprogrammed slot.
    """
    memory = module.get_memory()
    ranges = action_ranges(module)
    if memory is None or not ranges:
        return None

    blocks = []
    for start, length in ranges:
        data = memory.get_cached_range(start, length)
        if data is None:
            continue
        blocks.append({"start": start, "data": data.hex()})
    if not blocks:
        return None

    return {
        "version": CACHE_VERSION,
        "address": module.get_address(),
        "fingerprint": module_fingerprint(module),
        "read_at": time.time(),
        "blocks": blocks,
    }


def import_module_actions(module: Module, data: dict[str, Any]) -> float | None:
    """Feed cached bytes back into a module, returning when they were read.

    None means the entry was rejected: a different module, an older cache
    layout, or bytes that no longer line up with the ranges the tables use.
    """
    memory = module.get_memory()
    if memory is None:
        return None
    if data.get("version") != CACHE_VERSION:
        return None
    if data.get("fingerprint") != module_fingerprint(module):
        _LOGGER.debug(
            "Ignoring action cache for module %s: it was read from another module",
            module.get_address(),
        )
        return None

    wanted = dict(action_ranges(module))
    if not wanted:
        return None

    restored = False
    for block in data.get("blocks", ()):
        try:
            start = int(block["start"])
            raw = bytes.fromhex(str(block["data"]))
        except (KeyError, TypeError, ValueError):
            return None
        if wanted.get(start) != len(raw):
            _LOGGER.debug(
                "Ignoring action cache block at 0x%04X for module %s: the table "
                "no longer has that shape",
                start,
                module.get_address(),
            )
            continue
        memory.feed_block(start, raw)
        restored = True

    if not restored:
        return None
    # Anything parsed before these bytes arrived was parsed from other bytes.
    for table in module.get_action_tables().values():
        table.forget()
    read_at = data.get("read_at")
    return float(read_at) if isinstance(read_at, (int, float)) else 0.0


async def scan_module_actions(
    module: Module,
    *,
    force: bool = False,
    include_empty: bool = False,
    progress: BytesCallback | None = None,
) -> ModuleActions:
    """Read every action table of one module.

    Without ``force`` this is served from whatever the module already holds,
    which after ``load_action_cache()`` is the whole table and costs nothing.
    """
    result = ModuleActions(
        address=module.get_address(),
        name=module.get_name(),
        type_name=module.get_type_name(),
        read_at=time.time(),
    )
    tables: dict[int, ActionTable] = module.get_action_tables()
    if not tables:
        return result

    # "Free" is the useful question here, and the answer is whether the bytes
    # are already known -- which they are after load_action_cache(), even
    # though nothing has parsed them into slots yet.
    result.from_cache = not force and has_cached_actions(module)

    ranges = action_ranges(module)
    memory = module.get_memory()
    bytes_total = sum(length for _start, length in ranges)

    def report() -> None:
        if progress is None:
            return
        done = 0
        if memory is not None and not force:
            done = sum(
                length
                for start, length in ranges
                if memory.get_cached_range(start, length) is not None
            )
        progress(done, bytes_total)

    # A forced read starts over, so the bytes it already holds say nothing
    # about how far it has come; counting them would start the bar full.
    read_ranges: list[tuple[int, int]] = []

    def report_forced() -> None:
        if progress is None:
            return
        progress(sum(length for _start, length in read_ranges), bytes_total)

    if force:
        report_forced()
    else:
        report()

    for channel, table in sorted(tables.items()):
        try:
            slots = await table.get_actions(refresh=force, include_empty=include_empty)
        except Exception as err:  # noqa: BLE001 - one module must not stop the scan
            result.error = str(err) or type(err).__name__
            _LOGGER.warning(
                "Could not read the action table of module %s channel %s: %s",
                module.get_address(),
                channel,
                err,
            )
            break
        result.channels[channel] = slots
        if force:
            table_range = (table.bank, table.slot_count * table.slot_size)
            if table_range not in read_ranges:
                read_ranges.append(table_range)
            if (
                table.noc_address is not None
                and (
                    table.noc_address,
                    1,
                )
                not in read_ranges
            ):
                read_ranges.append((table.noc_address, 1))
            report_forced()
        else:
            report()
    return result


async def scan_actions(
    controller: Velbus,
    *,
    force: bool = False,
    include_empty: bool = False,
    addresses: Iterable[int] | None = None,
    progress: ProgressCallback | None = None,
) -> ActionScan:
    """Read the action tables of every module that has one.

    Modules are read one after another on purpose. They share one bus and one
    serial link, so reading them at once does not go faster, and it does push
    every other message on the bus behind a queue of memory requests.
    """
    wanted = None if addresses is None else set(addresses)
    modules = [
        module
        for module in controller.get_modules().values()
        if module.get_action_tables()
        and (wanted is None or module.get_address() in wanted)
    ]
    modules.sort(key=lambda module: module.get_address())

    scan = ActionScan()
    started = time.monotonic()
    for index, module in enumerate(modules):

        def report(
            bytes_done: int,
            bytes_total: int,
            index: int = index,
            module: Module = module,
        ) -> None:
            if progress is None:
                return
            progress(
                ScanProgress(
                    done=index,
                    total=len(modules),
                    address=module.get_address(),
                    name=module.get_name(),
                    bytes_done=bytes_done,
                    bytes_total=bytes_total,
                )
            )

        scan.modules[module.get_address()] = await scan_module_actions(
            module, force=force, include_empty=include_empty, progress=report
        )
    scan.duration = time.monotonic() - started

    if progress is not None and modules:
        last = modules[-1]
        read = sum(length for _start, length in action_ranges(last))
        progress(
            ScanProgress(
                done=len(modules),
                total=len(modules),
                address=last.get_address(),
                name=last.get_name(),
                bytes_done=read,
                bytes_total=read,
            )
        )
    return scan


def has_cached_actions(module: Module) -> bool:
    """Return whether every byte of this module's tables is already known."""
    memory = module.get_memory()
    ranges = action_ranges(module)
    if memory is None or not ranges:
        return False
    return all(
        memory.get_cached_range(start, length) is not None for start, length in ranges
    )


async def cached_actions(
    controller: Velbus, *, include_empty: bool = False
) -> ActionScan:
    """Return the action tables that are known, without touching the bus.

    This is what a user interface should call to draw itself: a module that has
    never been scanned is left out rather than silently costing a minute of bus
    traffic in the middle of a page load.
    """
    scan = ActionScan()
    for module in sorted(
        controller.get_modules().values(), key=lambda item: item.get_address()
    ):
        if not has_cached_actions(module):
            continue
        scan.modules[module.get_address()] = await scan_module_actions(
            module, include_empty=include_empty
        )
    return scan


def cache_path(cache_dir: str, address: int) -> pathlib.Path:
    """Return the file holding one module's cached action tables."""
    return pathlib.Path(cache_dir) / f"{address}{CACHE_SUFFIX}"


async def save_action_cache(
    controller: Velbus, *, addresses: Iterable[int] | None = None
) -> list[int]:
    """Write what is known about the action tables to the cache directory.

    Returns the addresses that were written. A module whose tables were never
    read has nothing to write and is skipped rather than emptied, so a failed
    scan does not throw away an earlier good one.
    """
    wanted = None if addresses is None else set(addresses)
    cache_dir = controller.get_cache_dir()
    await anyio.Path(cache_dir).mkdir(parents=True, exist_ok=True)

    written: list[int] = []
    for module in controller.get_modules().values():
        address = module.get_address()
        if wanted is not None and address not in wanted:
            continue
        data = export_module_actions(module)
        if data is None:
            continue
        path = cache_path(cache_dir, address)
        # Same atomic dance as the module cache: write beside the target and
        # rename, so a reader never sees half a file.
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        async with await anyio.open_file(tmp, "w") as handle:
            await handle.write(json.dumps(data))
        await anyio.Path(tmp).rename(path)
        written.append(address)
    return written


async def load_action_cache(controller: Velbus) -> dict[int, float]:
    """Restore cached action bytes into the modules that are on the bus.

    Returns, per address, when those bytes were read from the module, so a
    caller can tell the user how old what they are looking at is.
    """
    cache_dir = controller.get_cache_dir()
    loaded: dict[int, float] = {}
    for module in controller.get_modules().values():
        address = module.get_address()
        path = cache_path(cache_dir, address)
        try:
            async with await anyio.open_file(path) as handle:
                data = json.loads(await handle.read())
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as err:
            _LOGGER.warning("Could not read the action cache of %s: %s", address, err)
            continue
        read_at = import_module_actions(module, data)
        if read_at is not None:
            loaded[address] = read_at
    return loaded


async def clear_action_cache(
    controller: Velbus, *, addresses: Iterable[int] | None = None
) -> list[int]:
    """Delete cached action tables so the next scan reads the bus again."""
    wanted = None if addresses is None else set(addresses)
    cache_dir = controller.get_cache_dir()
    removed: list[int] = []
    for module in controller.get_modules().values():
        address = module.get_address()
        if wanted is not None and address not in wanted:
            continue
        memory = module.get_memory()
        if memory is not None:
            for start, length in action_ranges(module):
                memory.invalidate(start, start + length - 1)
        for table in module.get_action_tables().values():
            table.forget()
        try:
            await anyio.Path(cache_path(cache_dir, address)).unlink()
        except FileNotFoundError:
            continue
        removed.append(address)
    return removed
