from __future__ import annotations

import random

from .catalog import CatalogResolver
from .configuration import AppConfig
from .constants import (
    DEFAULT_FLOAT_VALUE,
    DEFAULT_WEAPON_QUALITY_VALUE,
    FLOAT_ATTRIBUTE_ID,
    FLOAT_NORMALIZATION_OFFSET,
    GLOVE_DEF_INDEXES,
    KNIFE_DEF_INDEXES,
    LEGACY_INVENTORY_VALUE,
    PAINT_ATTRIBUTE_ID,
    PATTERN_ATTRIBUTE_ID,
    STATTRAK_COUNTER_ATTRIBUTE_ID,
    STATTRAK_KILLS_MAX,
    STATTRAK_KILLS_MIN,
    STATTRAK_QUALITY_VALUE,
    STATTRAK_SCORE_TYPE_ATTRIBUTE_ID,
    STATTRAK_SCORE_TYPE_VALUE,
    KNIFE_QUALITY_VALUE,
)
from .models import FinalizeStats, InventoryDocument, InventoryItem
from .runtime import LOGGER
from .text import (
    normalize_pattern_seed,
    normalize_paint_index,
    offset_min_float_value,
)


def is_painted_item(item: InventoryItem) -> bool:
    return bool(normalize_paint_index(item.attributes.get(PAINT_ATTRIBUTE_ID, "")))


def is_weapon_skin_item(item: InventoryItem) -> bool:
    return (
        is_painted_item(item)
        and item.def_index not in KNIFE_DEF_INDEXES
        and item.def_index not in GLOVE_DEF_INDEXES
    )


def resolve_lowest_supported_float(
    item: InventoryItem,
    resolver: CatalogResolver,
) -> str:
    resolved_float: str = resolver.get_lowest_float_value(item)
    if resolved_float:
        return resolved_float
    return offset_min_float_value(DEFAULT_FLOAT_VALUE, FLOAT_NORMALIZATION_OFFSET)


def resolve_stattrak_kill_count(
    item: InventoryItem,
    *,
    randomize_missing: bool,
) -> tuple[str, bool]:
    existing_value: str = item.attributes.get(STATTRAK_COUNTER_ATTRIBUTE_ID, "").strip()
    if existing_value:
        try:
            parsed_value = int(float(existing_value))
        except ValueError:
            parsed_value = None
        if (
            parsed_value is not None
            and STATTRAK_KILLS_MIN <= parsed_value <= STATTRAK_KILLS_MAX
        ):
            return str(parsed_value), False

    if randomize_missing:
        return str(random.randint(STATTRAK_KILLS_MIN, STATTRAK_KILLS_MAX)), True
    return str(STATTRAK_KILLS_MIN), False


def strip_stattrak_state(
    item: InventoryItem,
    replacement_quality: str | None = None,
) -> bool:
    changed = False
    for attribute_id in (
        STATTRAK_COUNTER_ATTRIBUTE_ID,
        STATTRAK_SCORE_TYPE_ATTRIBUTE_ID,
    ):
        if attribute_id in item.attributes:
            item.attributes.pop(attribute_id)
            changed = True

    if (
        replacement_quality is not None
        and item.quality == STATTRAK_QUALITY_VALUE
        and item.quality != replacement_quality
    ):
        item.quality = replacement_quality
        changed = True

    return changed


def resolve_case_hardened_blue_gem_seed(
    item: InventoryItem,
    resolver: CatalogResolver,
    config: AppConfig,
    stats: FinalizeStats,
) -> None:
    if not config.features.resolve_case_hardened_blue_gem:
        return
    if not resolver.is_case_hardened(item):
        return

    override_seed: str = normalize_pattern_seed(
        config.case_hardened.preferred_seed_overrides.get(item.def_index, "")
    )
    seed_candidates: tuple[str, ...] = resolver.get_case_hardened_seed_candidates(item)
    selected_seed: str = override_seed or (
        seed_candidates[0] if seed_candidates else ""
    )
    if not selected_seed:
        return

    current_seed: str = normalize_pattern_seed(
        item.attributes.get(PATTERN_ATTRIBUTE_ID, "")
    )
    if current_seed == selected_seed:
        return

    if len(seed_candidates) > 1 and not override_seed:
        LOGGER.debug(
            "Using first best-known blue gem seed %s for def_index %s from %s",
            selected_seed,
            item.def_index,
            ", ".join(seed_candidates),
        )

    item.attributes[PATTERN_ATTRIBUTE_ID] = selected_seed
    stats.case_hardened_patterns_resolved += 1
    LOGGER.debug(
        "Resolved %s to Case Hardened blue gem seed %s",
        resolver.describe_item_name(item),
        selected_seed,
    )


def resolve_fade_full_fade_seed(
    item: InventoryItem,
    resolver: CatalogResolver,
    config: AppConfig,
    stats: FinalizeStats,
) -> None:
    if not config.features.resolve_fade_full_fade:
        return
    if not resolver.is_fade(item):
        return

    override_seed: str = normalize_pattern_seed(
        config.fade.preferred_seed_overrides.get(item.def_index, "")
    )
    seed_candidates: tuple[str, ...] = resolver.get_fade_seed_candidates(item)
    selected_seed: str = override_seed or (
        seed_candidates[0] if seed_candidates else ""
    )
    if not selected_seed:
        return

    current_seed: str = normalize_pattern_seed(
        item.attributes.get(PATTERN_ATTRIBUTE_ID, "")
    )
    if current_seed == selected_seed:
        return

    if len(seed_candidates) > 1 and not override_seed:
        LOGGER.debug(
            "Using first best-known full-fade seed %s for def_index %s from %s",
            selected_seed,
            item.def_index,
            ", ".join(seed_candidates),
        )

    item.attributes[PATTERN_ATTRIBUTE_ID] = selected_seed
    stats.fade_patterns_resolved += 1
    LOGGER.debug(
        "Resolved %s to Fade full-fade seed %s",
        resolver.describe_item_name(item),
        selected_seed,
    )


def normalize_stattrak_state(
    item: InventoryItem,
    resolver: CatalogResolver,
    config: AppConfig,
    stats: FinalizeStats,
) -> None:
    if item.def_index in KNIFE_DEF_INDEXES:
        if config.features.strip_knife_stattrak and strip_stattrak_state(
            item, KNIFE_QUALITY_VALUE
        ):
            stats.knives_stattrak_removed += 1
        return

    if not is_weapon_skin_item(item):
        return

    stattrak_support: bool | None = resolver.get_stattrak_support(item)
    if stattrak_support is False:
        if config.features.clean_unsupported_weapon_stattrak and strip_stattrak_state(
            item, DEFAULT_WEAPON_QUALITY_VALUE
        ):
            stats.unsupported_weapon_stattrak_removed += 1
        return

    if stattrak_support is None or not config.features.force_weapon_stattrak:
        return

    changed = False
    if item.quality != STATTRAK_QUALITY_VALUE:
        item.quality = STATTRAK_QUALITY_VALUE
        changed = True

    kill_count, randomized = resolve_stattrak_kill_count(
        item,
        randomize_missing=config.features.randomize_weapon_kill_counters,
    )
    if item.attributes.get(STATTRAK_COUNTER_ATTRIBUTE_ID) != kill_count:
        item.attributes[STATTRAK_COUNTER_ATTRIBUTE_ID] = kill_count
        changed = True
    if (
        item.attributes.get(STATTRAK_SCORE_TYPE_ATTRIBUTE_ID)
        != STATTRAK_SCORE_TYPE_VALUE
    ):
        item.attributes[STATTRAK_SCORE_TYPE_ATTRIBUTE_ID] = STATTRAK_SCORE_TYPE_VALUE
        changed = True

    if changed:
        stats.weapons_stattrak_forced += 1
    if randomized:
        stats.weapon_kill_counters_randomized += 1


def normalize_inventory(
    document: InventoryDocument,
    resolver: CatalogResolver,
    config: AppConfig,
    stats: FinalizeStats,
) -> None:
    LOGGER.info("Normalizing %d inventory items", len(document.items))
    for item in document.items:
        has_float: bool = FLOAT_ATTRIBUTE_ID in item.attributes
        has_paint = bool(item.attributes.get(PAINT_ATTRIBUTE_ID, "").strip())
        if config.features.normalize_float_values:
            target_float: str = (
                resolve_lowest_supported_float(item, resolver) if has_paint else ""
            )
            if has_float:
                if target_float and item.attributes[FLOAT_ATTRIBUTE_ID] != target_float:
                    stats.zeroed_float_items += 1
                if target_float:
                    item.attributes[FLOAT_ATTRIBUTE_ID] = target_float
            elif target_float:
                item.attributes[FLOAT_ATTRIBUTE_ID] = target_float
                stats.added_float_items += 1

        resolve_case_hardened_blue_gem_seed(item, resolver, config, stats)
        resolve_fade_full_fade_seed(item, resolver, config, stats)
        normalize_stattrak_state(item, resolver, config, stats)

    deduped_items: list[InventoryItem] = document.items
    if config.features.dedupe_items:
        dedupe_seen: set[tuple[str, str, str, str, str]] = set()
        deduped_items = []
        for item in document.items:
            paint_index: str = normalize_paint_index(
                item.attributes.get(PAINT_ATTRIBUTE_ID, "")
            )
            if paint_index:
                dedupe_key: tuple[str, str, str, str, str] = resolver.build_dedupe_key(
                    item
                )
                if dedupe_key in dedupe_seen:
                    stats.removed_duplicates += 1
                    continue
                dedupe_seen.add(dedupe_key)
            deduped_items.append(item)

    document.items = deduped_items

    next_id = 2
    for item in document.items:
        item.id = str(next_id)
        if config.features.pin_inventory_value:
            item.inventory = LEGACY_INVENTORY_VALUE
        next_id += 1

    LOGGER.info(
        "Normalization complete: %d items kept, %d duplicates removed, %d wear values normalized, %d wear values added",
        len(document.items),
        stats.removed_duplicates,
        stats.zeroed_float_items,
        stats.added_float_items,
    )
    LOGGER.info(
        "StatTrak normalization complete: %d supported weapon skins forced, %d kill counters randomized, %d knives stripped, %d unsupported weapon skins cleaned",
        stats.weapons_stattrak_forced,
        stats.weapon_kill_counters_randomized,
        stats.knives_stattrak_removed,
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
