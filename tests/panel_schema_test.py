"""Tests for panel_schema."""

from pathlib import Path

import pytest

from velbusaio.panel_schema import get_module_type_schema, load_module_spec


def test_load_module_spec_merges_global_properties() -> None:
    """Global properties should be present when not overridden by the module spec."""
    spec = load_module_spec(0x08)
    assert "bus_error_off" in spec.get("Properties", {})
    assert spec["Type"] == "VMB4RY"


def test_vmb4ry_schema_sections() -> None:
    """VMB4RY should expose channels, names, and relay action programming."""
    schema = get_module_type_schema(0x08)
    assert schema["type_name"] == "VMB4RY"
    section_types = [section["type"] for section in schema["sections"]]
    assert section_types == [
        "channels",
        "channel_names",
        "contact",
        "action_table",
        "properties",
    ]

    action_section = next(
        section for section in schema["sections"] if section["type"] == "action_table"
    )
    assert action_section["catalog_id"] == "relay_classic"
    assert action_section["channels"] == [1, 2, 3, 4]
    assert any(action["key"] == "toggle" for action in action_section["actions"])
    contact_section = next(
        section for section in schema["sections"] if section["type"] == "contact"
    )
    assert contact_section["channels"] == [1, 2, 3, 4]
    assert contact_section["options"] == ["NO", "NC"]


@pytest.mark.parametrize(
    ("type_id", "type_name"),
    [
        pytest.param(0x08, "VMB4RY", id="vmb4ry"),
        pytest.param(0x01, "VMB8PB", id="vmb8pb"),
    ],
)
def test_schema_for_known_modules(type_id: int, type_name: str) -> None:
    """Known module specs should resolve to the expected type name."""
    schema = get_module_type_schema(type_id)
    assert schema["type_name"] == type_name
    assert schema["type_id"] == type_id
    assert schema["sections"]


def test_schema_for_missing_module_type() -> None:
    """Missing module specs should still merge global properties."""
    schema = get_module_type_schema(0xFE)
    assert schema["type_id"] == 0xFE
    assert schema["type_name"] == "0xFE"
    assert schema["sections"] == [
        {
            "id": "properties",
            "type": "properties",
            "properties": [
                {
                    "key": "bus_error_off",
                    "name": "Bus Error Off",
                    "property_type": "BusErrorOff",
                },
                {
                    "key": "bus_error_rx",
                    "name": "Bus Error Receive",
                    "property_type": "BusErrorRx",
                },
                {
                    "key": "bus_error_tx",
                    "name": "Bus Error Transmit",
                    "property_type": "BusErrorTx",
                },
            ],
        }
    ]


def test_action_catalog_matches_repo_file() -> None:
    """Action options should come from the relay_classic catalog."""
    schema = get_module_type_schema(0x08)
    action_section = next(
        section for section in schema["sections"] if section["type"] == "action_table"
    )
    catalog_path = (
        Path(__file__).resolve().parents[1]
        / "velbusaio/action_catalogs/relay_classic.json"
    )
    assert catalog_path.is_file()
    assert len(action_section["actions"]) > 0


def test_vmb4dc_schema_includes_dimmer_actions() -> None:
    """VMB4DC should expose dimmer action programming."""
    schema = get_module_type_schema(0x12)
    assert schema["type_name"] == "VMB4DC"
    action_section = next(
        section for section in schema["sections"] if section["type"] == "action_table"
    )
    assert action_section["catalog_id"] == "dimmer_classic"
    assert action_section["channels"] == [1, 2, 3, 4]
    assert any(action["key"] == "slow_on" for action in action_section["actions"])
    assert any(action["key"] == "toggle" for action in action_section["actions"])


def test_vmbdmi_schema_includes_dimmer_actions() -> None:
    """VMBDMI should expose a single-channel dimmer action table."""
    schema = get_module_type_schema(0x15)
    action_section = next(
        section for section in schema["sections"] if section["type"] == "action_table"
    )
    assert action_section["catalog_id"] == "dimmer_classic"
    assert action_section["channels"] == [1]


def test_vmb2ble_schema_includes_blind_actions() -> None:
    """VMB2BLE should expose classic blind action programming."""
    schema = get_module_type_schema(0x1D)
    action_section = next(
        section for section in schema["sections"] if section["type"] == "action_table"
    )
    assert action_section["catalog_id"] == "blind_classic"
    assert action_section["slot_size"] == 5
    assert action_section["channels"] == [1, 2]
    assert any(action["key"] == "up_down" for action in action_section["actions"])


def test_vmb2dc20_schema_includes_shared_dimmer_actions() -> None:
    """VMB2DC-20 should expose shared dimmer_v2 action programming."""
    schema = get_module_type_schema(0x24)
    action_section = next(
        section for section in schema["sections"] if section["type"] == "action_table"
    )
    assert action_section["catalog_id"] == "dimmer_v2"
    assert action_section["layout"] == "shared"
    assert action_section["slot_size"] == 6
    assert action_section["channels"] == [1, 2]


def test_vmb2ble20_schema_includes_shared_blind_actions() -> None:
    """VMB2BLE-20 should expose shared blind_v2 action programming."""
    schema = get_module_type_schema(0x61)
    action_section = next(
        section for section in schema["sections"] if section["type"] == "action_table"
    )
    assert action_section["catalog_id"] == "blind_v2"
    assert action_section["layout"] == "shared"
    assert any(action["key"] == "direct_up" for action in action_section["actions"])


def test_vmb8pbu_schema_includes_channel_enable() -> None:
    """VMB8PBU should expose per-channel enable/disable support."""
    schema = get_module_type_schema(0x16)
    enable_section = next(
        section for section in schema["sections"] if section["type"] == "channel_enable"
    )
    assert enable_section["channels"] == [1, 2, 3, 4, 5, 6, 7, 8]
    channels_section = next(
        section for section in schema["sections"] if section["type"] == "channels"
    )
    assert all(entry["supports_enable"] for entry in channels_section["channels"])
    action_section = next(
        section for section in schema["sections"] if section["type"] == "action_table"
    )
    assert action_section["kind"] == "input"
    assert action_section["catalog_id"] == "input_classic"


def test_vmb6pb20_schema_includes_channel_enable() -> None:
    """VMB6PB-20 should expose reaction-time based channel enable."""
    schema = get_module_type_schema(0x4C)
    enable_section = next(
        section for section in schema["sections"] if section["type"] == "channel_enable"
    )
    assert enable_section["channels"] == [1, 2, 3, 4, 5, 6, 7, 8]
    spec = load_module_spec(0x4C)
    assert spec["Memory"]["ChannelEnable"]["channels"]["01"] == "0010"
    assert spec["Memory"]["ChannelEnable"]["channels"]["02"] == "0024"


def test_vmb6pb20_schema_includes_input_v2_actions() -> None:
    """VMB6PB-20 should expose shared input_v2 action programming."""
    schema = get_module_type_schema(0x4C)
    action_section = next(
        section for section in schema["sections"] if section["type"] == "action_table"
    )
    assert action_section["kind"] == "input"
    assert action_section["catalog_id"] == "input_v2"
    assert action_section["layout"] == "shared"
    assert any(
        action["key"] == "select_program_group_1"
        for action in action_section["actions"]
    )
