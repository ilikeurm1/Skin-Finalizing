from __future__ import annotations

import argparse
import json
from pathlib import Path

from .gui import SelectionCanceledError
from .utils.catalog import CatalogResolver
from .utils.configuration import get_project_root, load_config, resolve_inventory_path
from .utils.keyvalues import (
    KeyValueParseError,
    parse_inventory_document,
    serialize_inventory_document,
)
from .utils.loadout import rebuild_equips
from .utils.models import FinalizeStats
from .utils.normalization import normalize_inventory
from .utils.runtime import (
    LOGGER,
    configure_logging,
    create_backup,
    read_text,
    write_text,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Finalize a csgo_gc inventory.txt file after GUI editing."
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to cfg.json. Defaults to skin_finalizing/src/cfg.json.",
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Optional inventory.txt override. Defaults to inventory_dir from cfg.json.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file path. Defaults to the input path.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Do not prompt for loadout choices. Overrides cfg.json interactive_mode.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create a timestamped backup when overwriting the input file.",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Console log verbosity override. Defaults to cfg.json log_level.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config, config_path = load_config(
            Path(args.config).resolve() if args.config else None
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Failed to load cfg.json: {exc}")
        return 1

    project_root = get_project_root()
    log_path = configure_logging(project_root, args.log_level or config.log_level)
    input_path = resolve_inventory_path(config, config_path, cli_input=args.input)
    output_path = Path(args.output).resolve() if args.output else input_path
    non_interactive = args.non_interactive or not config.interactive_mode

    LOGGER.info("Using config %s", config_path)
    LOGGER.info("Logging to %s", log_path)
    LOGGER.info("Starting inventory finalization")
    LOGGER.debug(
        "Resolved arguments: input=%s output=%s non_interactive=%s no_backup=%s",
        input_path,
        output_path,
        non_interactive,
        args.no_backup,
    )

    if not input_path.exists():
        LOGGER.error("Input file not found: %s", input_path)
        return 1

    original_text = read_text(input_path)
    try:
        document = parse_inventory_document(original_text)
    except KeyValueParseError as exc:
        LOGGER.error("Failed to parse inventory file: %s", exc)
        return 1

    resolver = CatalogResolver()
    LOGGER.info("Loading catalog data")
    resolver.load()

    stats = FinalizeStats()
    normalize_inventory(document, resolver, config, stats)
    try:
        rebuild_equips(
            document,
            resolver,
            non_interactive,
            stats,
            rebuild_default_equips=config.features.rebuild_default_equips,
        )
    except SelectionCanceledError as exc:
        LOGGER.warning(str(exc))
        return 1

    finalized_text = serialize_inventory_document(document)
    if finalized_text == original_text and input_path == output_path:
        LOGGER.info("No changes were necessary.")
        return 0

    if input_path == output_path and config.create_backup and not args.no_backup:
        backup_path = create_backup(input_path)
        LOGGER.info("Backup written to %s", backup_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_text(output_path, finalized_text)
    LOGGER.info("Finalized inventory written to %s", output_path)
    LOGGER.info("Items kept: %d", len(document.items))
    LOGGER.info("Wear values normalized: %d", stats.zeroed_float_items)
    LOGGER.info("Wear values added: %d", stats.added_float_items)
    LOGGER.info("Duplicates removed: %d", stats.removed_duplicates)
    LOGGER.info("Weapons forced to StatTrak: %d", stats.weapons_stattrak_forced)
    LOGGER.info(
        "Weapon kill counters randomized: %d",
        stats.weapon_kill_counters_randomized,
    )
    LOGGER.info("Knives stripped of StatTrak: %d", stats.knives_stattrak_removed)
    LOGGER.info(
        "Unsupported weapon skins stripped of invalid StatTrak: %d",
        stats.unsupported_weapon_stattrak_removed,
    )
    LOGGER.info(
        "Case Hardened blue gem patterns resolved: %d",
        stats.case_hardened_patterns_resolved,
    )
    LOGGER.info(
        "Fade full-fade patterns resolved: %d",
        stats.fade_patterns_resolved,
    )
    LOGGER.info("Auto-equipped slots: %d", stats.auto_equips)
    LOGGER.info("Prompted slots: %d", stats.prompted_equips)
    return 0
