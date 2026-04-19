from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field


@dataclass
class InventoryItem:
    original_id: str
    id: str
    inventory: str
    def_index: str
    level: str
    quality: str
    flags: str
    origin: str
    in_use: str
    rarity: str
    attributes: OrderedDict[str, str] = field(default_factory=OrderedDict)
    equipped_state: OrderedDict[str, str] = field(default_factory=OrderedDict)
    extra_fields: OrderedDict[str, object] = field(default_factory=OrderedDict)


@dataclass
class DefaultEquip:
    def_index: str
    class_id: str
    slot_id: str
    extra_fields: OrderedDict[str, object] = field(default_factory=OrderedDict)


@dataclass
class InventoryDocument:
    items: list[InventoryItem]
    default_equips: list[DefaultEquip]
    other_top_level: OrderedDict[str, object] = field(default_factory=OrderedDict)


@dataclass
class FinalizeStats:
    zeroed_float_items: int = 0
    added_float_items: int = 0
    removed_duplicates: int = 0
    auto_equips: int = 0
    prompted_equips: int = 0
    weapons_stattrak_forced: int = 0
    weapon_kill_counters_randomized: int = 0
    knives_stattrak_removed: int = 0
    unsupported_weapon_stattrak_removed: int = 0
    case_hardened_patterns_resolved: int = 0
    fade_patterns_resolved: int = 0


@dataclass
class SkinMetadata:
    name: str
    phase: str = ""
    pattern_name: str = ""
    pattern_id: str = ""
    image_url: str = ""
    min_float: str = ""
    max_float: str = ""
    seed_sensitive: bool = False
    supports_stattrak: bool = False


@dataclass
class LoadoutChoice:
    pair: tuple[str, str]
    label: str
    candidates: list[InventoryItem]
    current: InventoryItem | None
    default_item: InventoryItem
