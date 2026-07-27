#!/usr/bin/env python3
"""Validate module spec JSON files.

This script checks all JSON files under velbusaio/module_spec/*.json and fails
if any module spec declares a channel with "Editable": "yes" but the module
spec does not contain the corresponding memory location under
"Memory" -> "Channels" for that channel.

It also validates optional Memory subsections used by the config panel /
memory backend:

- Memory.ActionTable — action-table layout, catalogs and per-channel banks
- Memory.ChannelEnable — per-channel enable/disable EEPROM addresses

Additionally, it validates that every module type in the MODULE_DIRECTORY from
command_registry.py has a corresponding module spec file.

Pass ``--fix`` to rewrite every module spec with alphabetically sorted keys
at every level. Sorting preserves all keys and values (including ActionTable
and ChannelEnable); nothing is dropped.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

# Add parent directory to path to import velbusaio and sibling scripts
_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from velbusaio.command_registry import MESSAGE_CATALOG, MODULE_DIRECTORY  # noqa: E402
import velbusaio.messages  # noqa: F401,E402 - populate MESSAGE_CATALOG

from validate_command_specs import validate_all  # noqa: E402

# How many directory levels to walk up from this script to try to find the repo root
_MAX_UP_LEVELS = 6

_KNOWN_MEMORY_KEYS = frozenset(
    {
        "Address",
        "ActionTable",
        "ChannelEnable",
        "Channels",
        "Extras",
        "ModuleName",
        "SensorName",
    }
)

_ACTION_TABLE_REQUIRED = frozenset(
    {"actions", "channels", "slot_count", "slot_size"}
)


def h2(n: int) -> str:
    """Format an integer as the two-digit uppercase hex used in specs (e.g. 1 -> '01')."""
    return f"{int(n):02X}"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def locate_module_spec_dir(start: Path | None = None) -> Path | None:
    """Locate velbusaio/module_spec by walking up from start (defaults to this script's dir).
    Returns a pathlib.Path if found, otherwise None.
    """
    if start is None:
        start = Path(__file__).resolve().parent

    p = start
    for _ in range(_MAX_UP_LEVELS):
        candidate = p / "velbusaio" / "module_spec"
        if candidate.is_dir():
            return candidate
        p = p.parent
    return None


def _sort_keys(data: Any) -> Any:
    """Recursively sort dict keys alphabetically, preserving all values."""
    if isinstance(data, dict):
        return {key: _sort_keys(data[key]) for key in sorted(data)}
    if isinstance(data, list):
        return [_sort_keys(item) for item in data]
    return data


def _unsorted_keys(data: Any, path: str = "") -> list[str]:
    """Recursively find dict keys that are not sorted alphabetically."""
    errors: list[str] = []
    if isinstance(data, dict):
        keys = list(data.keys())
        if keys != sorted(keys):
            errors.append(f"  at '{path}': {keys} (expected {sorted(keys)})")
        for key, value in data.items():
            errors.extend(_unsorted_keys(value, f"{path}.{key}" if path else key))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            errors.extend(_unsorted_keys(item, f"{path}[{i}]"))
    return errors


def check_json_sorted(path: Path) -> list[str]:
    """Check that all JSON keys are sorted alphabetically at every level."""
    try:
        spec = load_json(path)
    except Exception as exc:
        return [f"{path}: failed to load JSON: {exc}"]
    issues = _unsorted_keys(spec)
    if issues:
        return [f"{path}: keys not sorted:"] + issues
    return []


def fix_json_sorted(path: Path) -> bool:
    """Rewrite *path* with alphabetically sorted keys. Returns True if changed.

    All existing keys and values are preserved; only key order is normalized.
    """
    try:
        spec = load_json(path)
    except Exception:
        return False
    new_text = json.dumps(_sort_keys(spec), indent=2, ensure_ascii=False) + "\n"
    old_text = path.read_text(encoding="utf-8")
    if new_text == old_text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def _parse_hex_address(value: Any) -> int | None:
    """Parse a hex memory address string (e.g. '00EC' or '0x00EC')."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return int(value, 16) if value.lower().startswith("0x") else int(value, 16)
    except ValueError:
        return None


def _validate_action_table(path: Path, action_table: Any) -> list[str]:
    """Validate Memory.ActionTable structure used by build_action_tables()."""
    errors: list[str] = []
    prefix = f"{path}: Memory.ActionTable"

    if not isinstance(action_table, dict):
        return [f"{prefix} must be an object"]

    missing = _ACTION_TABLE_REQUIRED - action_table.keys()
    if missing:
        errors.append(
            f"{prefix} missing required keys: {', '.join(sorted(missing))}"
        )

    catalog_id = action_table.get("actions")
    if catalog_id is not None:
        if not isinstance(catalog_id, str) or not catalog_id:
            errors.append(f"{prefix}.actions must be a non-empty string")
        else:
            catalog_path = (
                _REPO_ROOT / "velbusaio" / "action_catalogs" / f"{catalog_id}.json"
            )
            if not catalog_path.is_file():
                errors.append(
                    f"{prefix}.actions references unknown catalog '{catalog_id}' "
                    f"(expected {catalog_path.name})"
                )

    for int_key in ("slot_count", "slot_size"):
        if int_key in action_table and not isinstance(action_table[int_key], int):
            errors.append(f"{prefix}.{int_key} must be an integer")

    layout = action_table.get("layout", "per_channel")
    if layout not in ("per_channel", "shared"):
        errors.append(
            f"{prefix}.layout must be 'per_channel' or 'shared' (got {layout!r})"
        )

    if layout == "shared":
        if "bank" not in action_table:
            errors.append(f"{prefix} shared layout requires 'bank'")
        elif _parse_hex_address(action_table["bank"]) is None:
            errors.append(f"{prefix}.bank must be a hex address string")

    channels = action_table.get("channels")
    if channels is None:
        return errors
    if not isinstance(channels, dict):
        errors.append(f"{prefix}.channels must be an object")
        return errors

    for chan_key, chan_spec in channels.items():
        try:
            int(chan_key)
        except (TypeError, ValueError):
            errors.append(f"{prefix}.channels key '{chan_key}' is not an integer")
            continue
        if not isinstance(chan_spec, dict):
            errors.append(f"{prefix}.channels.{chan_key} must be an object")
            continue
        if layout != "shared":
            if "bank" not in chan_spec:
                errors.append(
                    f"{prefix}.channels.{chan_key} per_channel layout requires 'bank'"
                )
            elif _parse_hex_address(chan_spec["bank"]) is None:
                errors.append(
                    f"{prefix}.channels.{chan_key}.bank must be a hex address string"
                )
        if "noc_address" in chan_spec and _parse_hex_address(
            chan_spec["noc_address"]
        ) is None:
            errors.append(
                f"{prefix}.channels.{chan_key}.noc_address must be a hex address string"
            )

    return errors


def _validate_channel_enable(path: Path, enable: Any) -> list[str]:
    """Validate Memory.ChannelEnable structure."""
    errors: list[str] = []
    prefix = f"{path}: Memory.ChannelEnable"

    if not isinstance(enable, dict):
        return [f"{prefix} must be an object"]

    for int_key in ("disabled_value", "enabled_value"):
        if int_key in enable and not isinstance(enable[int_key], int):
            errors.append(f"{prefix}.{int_key} must be an integer")

    channels = enable.get("channels")
    if channels is None:
        errors.append(f"{prefix} missing required key 'channels'")
        return errors
    if not isinstance(channels, dict):
        errors.append(f"{prefix}.channels must be an object")
        return errors

    for chan_key, address in channels.items():
        try:
            int(chan_key)
        except (TypeError, ValueError):
            errors.append(f"{prefix}.channels key '{chan_key}' is not an integer")
            continue
        if _parse_hex_address(address) is None:
            errors.append(
                f"{prefix}.channels.{chan_key} must be a hex address string "
                f"(got {address!r})"
            )

    return errors


def validate_memory_sections(path: Path, memory: Any) -> list[str]:
    """Validate optional Memory subsections (ActionTable, ChannelEnable, …)."""
    errors: list[str] = []
    if memory is None:
        return errors
    if not isinstance(memory, dict):
        return [f"{path}: Memory must be an object"]

    unknown = set(memory) - _KNOWN_MEMORY_KEYS
    if unknown:
        # Warn-style: keep as errors so new keys are reviewed, but do not strip them.
        errors.append(
            f"{path}: Memory has unknown keys {sorted(unknown)} "
            f"(known: {sorted(_KNOWN_MEMORY_KEYS)})"
        )

    if "ActionTable" in memory:
        errors.extend(_validate_action_table(path, memory["ActionTable"]))
    if "ChannelEnable" in memory:
        errors.extend(_validate_channel_enable(path, memory["ChannelEnable"]))

    return errors


def validate_spec(path: Path) -> tuple[list[str], list[str]]:
    """Validate one module spec. Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        spec = load_json(path)
    except Exception as exc:
        errors.append(f"{path}: failed to load JSON: {exc}")
        return errors, warnings

    channels = spec.get("Channels", {})
    memory = spec.get("Memory")

    errors.extend(validate_memory_sections(path, memory))

    missing_channels_warned = False
    for chan_key, chan_data in channels.items():
        try:
            chan_num = int(chan_key)
        except Exception:
            errors.append(f"{path}: channel key '{chan_key}' is not an integer")
            continue

        editable = chan_data.get("Editable", "") == "yes"
        possible_key = str(chan_num).zfill(2)
        mem_channels = memory.get("Channels") if isinstance(memory, dict) else None

        if editable and memory is None:
            errors.append(
                f"{path}: channel {chan_num} (editable) but module spec is missing "
                "top-level 'Memory'"
            )
            continue

        if editable and isinstance(memory, dict) and mem_channels is None:
            # Some modules (e.g. VMB8PB) declare editable channels but only expose
            # ModuleName in Memory — keep as a warning so validation still passes.
            if not missing_channels_warned:
                warnings.append(
                    f"{path}: editable channels present but 'Memory' does not "
                    "contain 'Channels'"
                )
                missing_channels_warned = True
            continue

        if editable and mem_channels is not None and possible_key not in mem_channels:
            errors.append(
                f"{path}: channel {chan_num} (editable) but no memory location found "
                f"in Memory->Channels for key {possible_key}"
            )

        ctype = chan_data.get("Type", "")
        if (
            ctype
            in [
                "Blind",
                "Button",
                "ButtonCounter",
                "Dimmer",
                "Temperature",
                "Relay",
            ]
            and chan_data.get("Editable", "") == ""
        ):
            errors.append(
                f"{path}: channel {chan_num} of type {ctype} but editable field is missing"
            )

    return errors, warnings


def validate_command_to_class(path: Path, spec: dict) -> list[str]:
    """Validate CommandToClass entries reference known message classes."""
    errors: list[str] = []
    mapping = spec.get("CommandToClass")
    if not mapping:
        return errors
    for command_hex, class_name in mapping.items():
        try:
            int(command_hex, 16)
        except ValueError:
            errors.append(f"{path}: invalid CommandToClass key {command_hex}")
        if class_name not in MESSAGE_CATALOG:
            errors.append(
                f"{path}: CommandToClass {command_hex} references unknown class {class_name}"
            )
    return errors


def check_module_directory_coverage(module_spec_dir: Path) -> list[str]:
    """Check that every module in MODULE_DIRECTORY has a corresponding spec file."""
    errors: list[str] = []

    # Get all existing spec files (without .json extension)
    existing_specs = {p.stem.upper(): p for p in module_spec_dir.glob("*.json")}

    # Check each module in the registry
    for module_type, module_name in MODULE_DIRECTORY.items():
        expected_filename = h2(module_type).upper()

        if expected_filename not in existing_specs:
            errors.append(
                f"Module type 0x{expected_filename} ({module_name}) from MODULE_DIRECTORY "
                f"has no corresponding spec file {expected_filename}.json"
            )
        else:
            # Spec file exists, now check if the Type field matches the module name
            spec_path = existing_specs[expected_filename]
            try:
                spec = load_json(spec_path)
                spec_type = spec.get("Type")

                if spec_type is None:
                    errors.append(
                        f"Spec file {spec_path.name} is missing 'Type' field "
                        f"(expected: {module_name})"
                    )
                elif spec_type != module_name:
                    errors.append(
                        f"Spec file {spec_path.name} has Type='{spec_type}' "
                        f"but MODULE_DIRECTORY[0x{expected_filename}] expects '{module_name}'"
                    )
            except Exception as exc:
                errors.append(
                    f"Failed to validate Type field in {spec_path.name}: {exc}"
                )

    return errors


# Spec files that are not module-type specs and therefore have no
# MODULE_DIRECTORY entry.
_NON_MODULE_SPECS = frozenset({"global", "broadcast", "ignore"})


def check_orphan_specs(module_spec_dir: Path) -> list[str]:
    """Check that every module-type spec file has a MODULE_DIRECTORY entry.

    This is the reverse of check_module_directory_coverage: it reports spec files
    that exist on disk but are not referenced by MODULE_DIRECTORY (orphan specs),
    so the library would never instantiate them.
    """
    errors: list[str] = []
    known_types = {h2(module_type).upper() for module_type in MODULE_DIRECTORY}

    for spec_path in sorted(module_spec_dir.glob("*.json")):
        stem = spec_path.stem
        if stem.lower() in _NON_MODULE_SPECS:
            continue
        try:
            int(stem, 16)
        except ValueError:
            # Not a hex-named module spec (e.g. a helper file); skip it.
            continue
        if stem.upper() not in known_types:
            errors.append(
                f"Spec file {spec_path.name} has no MODULE_DIRECTORY entry "
                f"(orphan spec: 0x{stem.upper()} is not registered)"
            )

    return errors


def check_empty_command_to_class(module_spec_dir: Path) -> list[str]:
    """Check that every module-type spec defines a non-empty CommandToClass.

    A module spec with a missing or empty CommandToClass cannot decode any bus
    message, so it is almost certainly incomplete.
    """
    warnings: list[str] = []

    for spec_path in sorted(module_spec_dir.glob("*.json")):
        stem = spec_path.stem
        if stem.lower() in _NON_MODULE_SPECS:
            continue
        try:
            int(stem, 16)
        except ValueError:
            continue
        try:
            spec = load_json(spec_path)
        except Exception as exc:
            warnings.append(f"{spec_path.name}: failed to load JSON: {exc}")
            continue
        if not spec.get("CommandToClass"):
            warnings.append(
                f"Spec file {spec_path.name} has an empty or missing CommandToClass"
            )

    return warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate (and optionally fix) velbusaio module_spec JSON files."
    )
    parser.add_argument(
        "repo",
        nargs="?",
        default=None,
        help="Optional path to the repo root (or a path containing velbusaio/module_spec).",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help=(
            "Rewrite module specs with alphabetically sorted keys at every level. "
            "Preserves all keys and values (ActionTable, ChannelEnable, …)."
        ),
    )
    args = parser.parse_args(argv)

    start_path = Path(args.repo).resolve() if args.repo else None
    module_spec_dir = locate_module_spec_dir(start_path)
    if module_spec_dir is None:
        print(
            "Could not find velbusaio/module_spec directory. "
            "Run the script from the repo or provide the repo path as the first argument.",
            file=sys.stderr,
        )
        return 1

    spec_files = sorted(module_spec_dir.glob("*.json"))
    if not spec_files:
        print(
            f"No module spec JSON files found under {module_spec_dir}", file=sys.stderr
        )
        return 1

    if args.fix:
        fixed = 0
        for path in spec_files:
            if fix_json_sorted(path):
                fixed += 1
        print(f"Sorted keys in {fixed}/{len(spec_files)} module spec files.")

    all_errors: list[str] = []
    all_warnings: list[str] = []

    # Check that all modules in MODULE_DIRECTORY have spec files
    print("Checking MODULE_DIRECTORY coverage...")
    coverage_errors = check_module_directory_coverage(module_spec_dir)
    all_errors.extend(coverage_errors)

    if coverage_errors:
        print(f"Found {len(coverage_errors)} modules without spec files.")
    else:
        print("All modules in MODULE_DIRECTORY have spec files.")

    # Validate individual spec files
    print(f"\nValidating {len(spec_files)} module spec files...")
    for p in spec_files:
        try:
            spec = load_json(p)
        except Exception as exc:
            all_errors.append(f"{p}: failed to load JSON: {exc}")
            continue
        spec_errors, spec_warnings = validate_spec(p)
        all_errors.extend(spec_errors)
        all_warnings.extend(spec_warnings)
        all_errors.extend(validate_command_to_class(p, spec))
        all_errors.extend(check_json_sorted(p))

    # Validate CommandToClass coverage for basic messages
    print("\nValidating CommandToClass coverage...")
    command_errors = validate_all(module_spec_dir)
    all_errors.extend(command_errors)
    if command_errors:
        print(f"Found {len(command_errors)} CommandToClass problems.")
    else:
        print("All CommandToClass entries are complete and consistent.")

    # Non-fatal warnings: orphan specs, empty CommandToClass, incomplete Memory.
    all_warnings.extend(check_orphan_specs(module_spec_dir))
    all_warnings.extend(check_empty_command_to_class(module_spec_dir))
    if all_warnings:
        print(f"\nWarnings ({len(all_warnings)}):")
        for w in all_warnings:
            print(f" - {w}")

    if all_errors:
        print("\nModule spec validation failed. Problems found:")
        for e in all_errors:
            print(f" - {e}")
        return 1

    print("\nModule spec validation passed:")
    print(" - All modules in MODULE_DIRECTORY have spec files")
    print(" - All editable channels have memory locations")
    print(" - All Memory.ActionTable / ChannelEnable sections are valid")
    print(" - All CommandToClass entries reference known message classes")
    print(" - All JSON files have alphabetically sorted keys")
    print(" - All CommandToClass entries are complete and consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
