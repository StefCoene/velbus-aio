---
paths:
  - "velbusaio/**"
  - "skills/velbus-ha-surface/**"
  - "tests/**"
---

# Velbus Home Assistant surface split

Canonical skill: `skills/velbus-ha-surface/SKILL.md`. Follow it when adding or reviewing anything exposed to Home Assistant.

| Surface         | Criterion                                                                                                |
| --------------- | -------------------------------------------------------------------------------------------------------- |
| **HA entity**   | Regular Velbus messages only — **no** internal memory (EEPROM) writes                                    |
| **Config page** | Needs internal memory writing (`MemoryBackend`, `0xFC`/`0xCA`, action tables, EEPROM names/NO-NC/enable) |

## Rules

- Bus-message controls → HA entities; set `ConfigParameter.entity=True` (default).
- EEPROM / `MemoryBackend` writes → config panel only; set `entity=False`, gate with advanced mode, expose via `panel_schema` + websocket — never as entities.
- One write surface per parameter; do not dual-expose.
- TempSensorSettings (Part1–4) are not EEPROM: allowed as `entity_category=config` entities.
- Names, NO/NC, channel enable, action-table links → config page only.
