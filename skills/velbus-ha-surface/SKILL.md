---
name: velbus-ha-surface
description: Decides whether a Velbus parameter belongs as a Home Assistant entity or on the Velbus config panel. Use when adding or reviewing HA entities, ConfigParameter definitions, panel_schema fields, websocket config APIs, or velbus-frontend module pages. Split is bus-message control vs internal memory (EEPROM) writes.
disable-model-invocation: false
---

# Velbus Home Assistant surface split

When exposing Velbus parameters to Home Assistant, choose **exactly one** surface:

| Surface         | Criterion                                                                        |
| --------------- | -------------------------------------------------------------------------------- |
| **HA entity**   | Controlled by regular Velbus messages — **no** writing to module internal memory |
| **Config page** | Requires writing module internal memory (EEPROM)                                 |

Do not expose the same write path on both surfaces.

## Entities (regular bus messages)

Expose as Home Assistant entities (platforms under `homeassistant/components/velbus/`) when the control path sends normal command/status frames and does **not** go through `MemoryBackend` / EEPROM write messages (`0xFC`, `0xCA`).

Typical examples:

- Relay on/off, dimmer brightness, cover open/close/position
- Climate setpoint, presets, heat/cool mode
- Sensors and binary sensors (status / measurement frames)
- Button press simulation, LED feedback, program select
- Relay inhibit / forced on / forced off (runtime bus commands)
- Temperature sensor settings via TempSensorSettings frames (Part1–4) — persistent, but **not** EEPROM/`MemoryBackend`; use `entity_category=config` number entities when appropriate

Mark discoverable params with `ConfigParameter(..., entity=True)` (the default).

## Config page (internal memory)

Put on the Velbus config panel (websocket API + `velbus-frontend` + `panel_schema`) when the write path uses module internal memory:

- `MemoryBackend` (`velbusaio/memory.py`)
- Channel names stored in EEPROM
- Relay NO/NC contact type
- Channel enable/disable via reaction-time / enable EEPROM bytes
- Action-table programming (input → output links)

Requirements for config-page writes:

- `ConfigParameter(..., entity=False)` — panel only; never create an HA entity for it
- Gate writes behind advanced mode (`require_advanced_mode` / `CONF_ADVANCED_MODE`)
- Surface via `panel_schema` + `velbus/config_panel/...` websocket commands, not entity platforms

## Decision checklist

```
- [ ] Does the setter write EEPROM / call MemoryBackend / program action tables?
      → YES: config page, entity=False, advanced mode
      → NO:  HA entity (optionally entity_category=config)
- [ ] Is the same value writable from both an entity and the panel?
      → Fix: keep a single write surface per the table above
```

## Code anchors

- `ConfigParameter.entity` — `velbusaio/config.py` (`False` = panel-only)
- Memory writes — `velbusaio/memory.py`, `module.set_channel_name_persistent`, `actions.py`
- Panel schema — `velbusaio/panel_schema.py`
- HA panel API — `homeassistant/components/velbus/websocket_api.py`
- Frontend — `velbus-frontend` module pages / `api.js`
