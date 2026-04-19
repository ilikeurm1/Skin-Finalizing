from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .constants import DEFAULT_LOG_LEVEL


@dataclass
class FeatureFlags:
    pin_inventory_value: bool = True
    normalize_float_values: bool = True
    force_weapon_stattrak: bool = True
    randomize_weapon_kill_counters: bool = True
    clean_unsupported_weapon_stattrak: bool = True
    strip_knife_stattrak: bool = True
    resolve_case_hardened_blue_gem: bool = True
    resolve_fade_full_fade: bool = True
    dedupe_items: bool = True
    rebuild_default_equips: bool = True


@dataclass
class CaseHardenedConfig:
    preferred_seed_overrides: dict[str, str] = field(default_factory=dict)


@dataclass
class FadeConfig:
    preferred_seed_overrides: dict[str, str] = field(default_factory=dict)


@dataclass
class AppConfig:
    inventory_dir: str
    log_level: str = DEFAULT_LOG_LEVEL
    create_backup: bool = True
    interactive_mode: bool = True
    features: FeatureFlags = field(default_factory=FeatureFlags)
    case_hardened: CaseHardenedConfig = field(default_factory=CaseHardenedConfig)
    fade: FadeConfig = field(default_factory=FadeConfig)


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_default_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "cfg.json"


def build_default_config() -> AppConfig:
    default_inventory = get_project_root().parent / "inventory.txt"
    return AppConfig(inventory_dir=str(default_inventory))


def save_config(config: AppConfig, config_path: Path | None = None) -> Path:
    target_path = config_path or get_default_config_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps(asdict(config), indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return target_path


def _normalize_string_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    result: dict[str, str] = {}
    for key, raw_value in value.items():
        result[str(key)] = str(raw_value)
    return result


def _read_bool(value: object, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    return fallback


def _read_string(value: object, fallback: str) -> str:
    if isinstance(value, str):
        return value
    return fallback


def load_config(config_path: Path | None = None) -> tuple[AppConfig, Path]:
    target_path = config_path or get_default_config_path()
    default_config = build_default_config()

    if not target_path.exists():
        save_config(default_config, target_path)
        return default_config, target_path

    raw_data = json.loads(target_path.read_text(encoding="utf-8"))
    if not isinstance(raw_data, dict):
        raise ValueError("cfg.json must contain a JSON object.")

    raw_features = raw_data.get("features")
    raw_case_hardened = raw_data.get("case_hardened")
    raw_fade = raw_data.get("fade")
    features = FeatureFlags(
        pin_inventory_value=_read_bool(
            (
                raw_features.get("pin_inventory_value")
                if isinstance(raw_features, dict)
                else None
            ),
            default_config.features.pin_inventory_value,
        ),
        normalize_float_values=_read_bool(
            (
                raw_features.get("normalize_float_values")
                if isinstance(raw_features, dict)
                else None
            ),
            default_config.features.normalize_float_values,
        ),
        force_weapon_stattrak=_read_bool(
            (
                raw_features.get("force_weapon_stattrak")
                if isinstance(raw_features, dict)
                else None
            ),
            default_config.features.force_weapon_stattrak,
        ),
        randomize_weapon_kill_counters=_read_bool(
            (
                raw_features.get("randomize_weapon_kill_counters")
                if isinstance(raw_features, dict)
                else None
            ),
            default_config.features.randomize_weapon_kill_counters,
        ),
        clean_unsupported_weapon_stattrak=_read_bool(
            (
                raw_features.get("clean_unsupported_weapon_stattrak")
                if isinstance(raw_features, dict)
                else None
            ),
            default_config.features.clean_unsupported_weapon_stattrak,
        ),
        strip_knife_stattrak=_read_bool(
            (
                raw_features.get("strip_knife_stattrak")
                if isinstance(raw_features, dict)
                else None
            ),
            default_config.features.strip_knife_stattrak,
        ),
        resolve_case_hardened_blue_gem=_read_bool(
            (
                raw_features.get("resolve_case_hardened_blue_gem")
                if isinstance(raw_features, dict)
                else None
            ),
            default_config.features.resolve_case_hardened_blue_gem,
        ),
        resolve_fade_full_fade=_read_bool(
            (
                raw_features.get("resolve_fade_full_fade")
                if isinstance(raw_features, dict)
                else None
            ),
            default_config.features.resolve_fade_full_fade,
        ),
        dedupe_items=_read_bool(
            (
                raw_features.get("dedupe_items")
                if isinstance(raw_features, dict)
                else None
            ),
            default_config.features.dedupe_items,
        ),
        rebuild_default_equips=_read_bool(
            (
                raw_features.get("rebuild_default_equips")
                if isinstance(raw_features, dict)
                else None
            ),
            default_config.features.rebuild_default_equips,
        ),
    )
    case_hardened = CaseHardenedConfig(
        preferred_seed_overrides=_normalize_string_map(
            raw_case_hardened.get("preferred_seed_overrides")
            if isinstance(raw_case_hardened, dict)
            else None
        )
    )
    fade = FadeConfig(
        preferred_seed_overrides=_normalize_string_map(
            raw_fade.get("preferred_seed_overrides")
            if isinstance(raw_fade, dict)
            else None
        )
    )
    config = AppConfig(
        inventory_dir=_read_string(
            raw_data.get("inventory_dir"), default_config.inventory_dir
        ),
        log_level=_read_string(raw_data.get("log_level"), default_config.log_level),
        create_backup=_read_bool(
            raw_data.get("create_backup"), default_config.create_backup
        ),
        interactive_mode=_read_bool(
            raw_data.get("interactive_mode"), default_config.interactive_mode
        ),
        features=features,
        case_hardened=case_hardened,
        fade=fade,
    )
    return config, target_path


def _coerce_inventory_candidate(candidate: str, config_path: Path) -> Path:
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = (config_path.parent / path).resolve()

    if path.is_dir():
        return path / "inventory.txt"
    return path


def prompt_for_inventory_path(initial_path: Path | None = None) -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        response = input(
            "Inventory path not found. Enter the full path to inventory.txt: "
        ).strip()
        if not response:
            return None
        return Path(response).expanduser().resolve()

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    selected_path = filedialog.askopenfilename(
        title="Select inventory.txt",
        initialdir=str(initial_path.parent if initial_path else get_project_root()),
        initialfile=initial_path.name if initial_path else "inventory.txt",
        filetypes=(
            ("Inventory files", "inventory.txt"),
            ("Text files", "*.txt"),
            ("All files", "*.*"),
        ),
    )
    root.destroy()
    if not selected_path:
        return None
    return Path(selected_path).expanduser().resolve()


def resolve_inventory_path(
    config: AppConfig,
    config_path: Path,
    cli_input: str | None = None,
) -> Path:
    if cli_input:
        return _coerce_inventory_candidate(cli_input, config_path)

    candidate_path = _coerce_inventory_candidate(config.inventory_dir, config_path)
    if candidate_path.exists():
        return candidate_path

    selected_path = prompt_for_inventory_path(candidate_path)
    if selected_path is None:
        raise FileNotFoundError(f"Input inventory file not found: {candidate_path}")

    config.inventory_dir = str(selected_path)
    save_config(config, config_path)
    return selected_path
