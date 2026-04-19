# Skin Finalizing

This project finalizes a legacy `csgo_gc` `inventory.txt` file after you add or edit skins. It can normalize item data, apply loadout choices through a GUI, resolve supported StatTrak values, convert Case Hardened skins to their best-known blue gem seeds, and convert Fade skins to best-known full-fade seeds.

## Folder Layout

```text
skin_finalizing/
├── .venv/
├── logs/
├── src/
│   ├── utils/
│   ├── __init__.py
│   ├── app.py
│   ├── gui.py
│   └── cfg.json
├── pyproject.toml
├── uv.lock
└── README.md
```

## What It Does

- Reads a legacy `inventory.txt` file and writes the finalized result back out.
- Keeps legacy-safe inventory values when enabled.
- Rebuilds `equipped_state` and `default_equips` from the selected loadout.
- Opens a Tkinter GUI when a slot has multiple candidate skins and interactive mode is enabled.
- Downloads weapon and skin metadata from the ByMykel CSGO API.
- Keeps a complete local fallback table of base weapon def indexes plus knife and glove variants so labels still work if API data is missing.
- Shows skin preview images in the GUI.
- Writes logs to the terminal and to the `logs/` folder.
- Can force StatTrak only on skins that actually support it.
- Can strip invalid StatTrak from unsupported skins and knives.
- Can resolve Case Hardened skins to best-known blue gem pattern seeds.
- Can resolve Fade skins to best-known full-fade pattern seeds.

## Configuration

The user-editable config file is `src/cfg.json`.

### Main Settings

- `inventory_dir`: Path to the target `inventory.txt`, or to the folder that contains it.
- `log_level`: Console log level.
- `create_backup`: Create a timestamped backup before overwriting the target file.
- `interactive_mode`: Use the GUI when ambiguous loadout choices exist.

### Feature Toggles

These are under `features` in `cfg.json`.

- `pin_inventory_value`: Keep each item's `inventory` value pinned to the legacy-safe value.
- `normalize_float_values`: Set each painted item to the skin's minimum supported float plus `0.0001`. Zero-start skins therefore become `0.0001`, and capped skins stay slightly above their minimum supported wear.
- `force_weapon_stattrak`: Apply StatTrak to supported weapon skins.
- `randomize_weapon_kill_counters`: Randomize missing or invalid StatTrak kills.
- `clean_unsupported_weapon_stattrak`: Remove StatTrak from unsupported finishes.
- `strip_knife_stattrak`: Remove StatTrak from knives.
- `resolve_case_hardened_blue_gem`: Replace Case Hardened pattern seeds with best-known blue gem seeds.
- `resolve_fade_full_fade`: Replace Fade pattern seeds with best-known full-fade seeds.
- `dedupe_items`: Remove duplicates using the current dedupe rules.
- `rebuild_default_equips`: Rebuild the `default_equips` section.

### Case Hardened Overrides

You can override the default blue gem seed for specific def indexes under:

```json
"case_hardened": {
  "preferred_seed_overrides": {
    "500": "670",
    "5035": "829"
  }
}
```

This is useful when a skin has multiple co-#1 or commonly accepted top seeds and you want a specific one.

### Fade Overrides

You can override the default full-fade seed for specific def indexes under:

```json
"fade": {
  "preferred_seed_overrides": {
    "60": "374",
    "507": "412",
    "64": "599"
  }
}
```

This is useful when a finish has multiple accepted top seeds, or when you prefer a specific full-fade color balance.

## Inventory Path Handling

The script always tries to resolve the inventory path from `cfg.json` first.

- If `inventory_dir` points to a file, that file is used.
- If `inventory_dir` points to a directory, `inventory.txt` inside that directory is used.
- If the target does not exist, the script opens a Tk file picker so you can select the file.
- After you choose a file, the selected path is written back to `src/cfg.json` automatically.

## Running The Project

From the project folder:

```powershell
uv run main
```

Useful options:

```powershell
uv run main --non-interactive
uv run main --no-backup
uv run main --output "C:\path\to\output_inventory.txt"
uv run main --log-level DEBUG
uv run main --config "C:\path\to\cfg.json"
```

You can also launch it from the workspace root through the compatibility wrapper:

```powershell
python .\skin_finalizing.py
```

## Logs And Backups

- Project logs are written under `logs/`.
- Inventory backups are written next to the target inventory file in an `inventory_backups/` folder.

## Modules

- `src/app.py`: Main entrypoint and CLI flow.
- `src/gui.py`: Tkinter loadout selector and preview UI.
- `src/utils/catalog.py`: API metadata loading and item label helpers.
- `src/utils/configuration.py`: Config loading, defaults, and inventory path resolution.
- `src/utils/keyvalues.py`: Valve KeyValues parsing and serialization.
- `src/utils/loadout.py`: Loadout choice collection and equip rebuilding.
- `src/utils/normalization.py`: Float, StatTrak, dedupe, Case Hardened, and Fade normalization.
- `src/utils/runtime.py`: Logging, backups, and file IO helpers.
- `src/utils/constants.py`: Shared constants, complete local def_index labels, and default Case Hardened / Fade seed mappings.
- `src/utils/models.py`: Dataclasses used across the project.
- `src/utils/text.py`: Formatting and normalization helpers.

## Notes

- The script depends on online API access for weapon names, skin metadata, and GUI image previews.
- If the API is unavailable, some labels or features may fall back to more basic behavior.
