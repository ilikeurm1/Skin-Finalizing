from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .constants import (
    BASE_WEAPONS_URL,
    CASE_HARDENED_BLUE_GEM_SEEDS,
    CASE_HARDENED_PATTERN_NAME,
    FADE_FULL_SEEDS,
    FADE_PATTERN_NAME,
    FLOAT_NORMALIZATION_OFFSET,
    GLOVE_DEF_INDEXES,
    KNIFE_DEF_INDEXES,
    PAINT_ATTRIBUTE_ID,
    PATTERN_ATTRIBUTE_ID,
    SKIN_API_URLS,
    STATTRAK_COUNTER_ATTRIBUTE_ID,
    WEAPON_NAMES,
)
from .models import InventoryItem, SkinMetadata
from .runtime import LOGGER
from .text import (
    offset_min_float_value,
    is_seed_sensitive_skin,
    normalize_float_value,
    normalize_paint_index,
    normalize_pattern_seed,
    normalize_scalar,
    skin_name_only,
)


class CatalogResolver:
    def __init__(self) -> None:
        self.weapon_names: dict[str, str] = dict(WEAPON_NAMES)
        self.skin_names: dict[tuple[str, str], str] = {}
        self.skin_metadata: dict[tuple[str, str], SkinMetadata] = {}

    def load(self) -> None:
        self._load_weapon_names()
        self._load_skin_names()

    def describe_item(self, item: InventoryItem) -> str:
        return self.format_item_label(item, include_id=True, include_details=True)

    def describe_item_name(self, item: InventoryItem) -> str:
        return self.format_item_label(item, include_id=False, include_details=False)

    def describe_item_details(self, item: InventoryItem) -> str:
        details: list[str] = []
        pattern_seed: str = normalize_pattern_seed(
            item.attributes.get(PATTERN_ATTRIBUTE_ID, "")
        )
        paint_index: str = normalize_paint_index(
            item.attributes.get(PAINT_ATTRIBUTE_ID, "")
        )
        if pattern_seed:
            details.append(f"seed {pattern_seed}")
        if paint_index:
            details.append(f"finish {paint_index}")
        return ", ".join(details)

    def format_item_label(
        self, item: InventoryItem, *, include_id: bool, include_details: bool
    ) -> str:
        weapon_name: str = self.weapon_names.get(
            item.def_index, f"def_index {item.def_index}"
        )
        paint_index: str = normalize_paint_index(
            item.attributes.get(PAINT_ATTRIBUTE_ID, "")
        )
        label: str = weapon_name
        if paint_index:
            metadata: SkinMetadata | None = self.lookup_skin_metadata(
                item.def_index, paint_index
            )
            skin_name: str = self.skin_names.get(
                (item.def_index, paint_index), f"Finish {paint_index}"
            )
            if metadata and metadata.name:
                skin_name = metadata.name
            label = f"{weapon_name} | {skin_name}"

            if metadata and metadata.phase:
                phase: str = metadata.phase.strip()
                if phase and phase.lower() not in label.lower():
                    label = f"{label} | {phase}"

            if include_details:
                details: str = self.describe_item_details(item)
                if details:
                    label = f"{label} [{details}]"

        if item.quality == "12":
            label = f"Souvenir {label}"
        elif STATTRAK_COUNTER_ATTRIBUTE_ID in item.attributes:
            label = f"StatTrak {label}"

        if include_id:
            return f"#{item.id} {label}"
        return label

    def get_item_image_url(self, item: InventoryItem) -> str:
        paint_index: str = normalize_paint_index(
            item.attributes.get(PAINT_ATTRIBUTE_ID, "")
        )
        if not paint_index:
            return ""

        metadata: SkinMetadata | None = self.lookup_skin_metadata(
            item.def_index, paint_index
        )
        if metadata is None:
            return ""
        return metadata.image_url

    def build_dedupe_key(self, item: InventoryItem) -> tuple[str, str, str, str, str]:
        paint_index: str = normalize_paint_index(
            item.attributes.get(PAINT_ATTRIBUTE_ID, "")
        )
        stattrak_marker: str = (
            "1" if STATTRAK_COUNTER_ATTRIBUTE_ID in item.attributes else "0"
        )
        pattern_seed: str = ""
        if self.is_seed_sensitive(item, paint_index):
            pattern_seed = normalize_pattern_seed(
                item.attributes.get(PATTERN_ATTRIBUTE_ID, "")
            )

        return (
            item.def_index,
            paint_index,
            item.quality,
            stattrak_marker,
            pattern_seed,
        )

    def is_seed_sensitive(
        self, item: InventoryItem, paint_index: str | None = None
    ) -> bool:
        resolved_paint_index: str = paint_index or normalize_paint_index(
            item.attributes.get(PAINT_ATTRIBUTE_ID, "")
        )
        if not resolved_paint_index:
            return False

        metadata: SkinMetadata | None = self.lookup_skin_metadata(
            item.def_index, resolved_paint_index
        )
        if metadata is not None:
            return metadata.seed_sensitive

        return (
            item.def_index in KNIFE_DEF_INDEXES or item.def_index in GLOVE_DEF_INDEXES
        )

    def lookup_skin_metadata(
        self, def_index: str, paint_index: str
    ) -> SkinMetadata | None:
        return self.skin_metadata.get((def_index, paint_index))

    def get_stattrak_support(self, item: InventoryItem) -> bool | None:
        paint_index: str = normalize_paint_index(
            item.attributes.get(PAINT_ATTRIBUTE_ID, "")
        )
        if not paint_index:
            return None

        metadata: SkinMetadata | None = self.lookup_skin_metadata(
            item.def_index, paint_index
        )
        if metadata is None:
            return None
        return metadata.supports_stattrak

    def is_case_hardened(self, item: InventoryItem) -> bool:
        paint_index: str = normalize_paint_index(
            item.attributes.get(PAINT_ATTRIBUTE_ID, "")
        )
        if not paint_index:
            return False

        metadata: SkinMetadata | None = self.lookup_skin_metadata(
            item.def_index, paint_index
        )
        if metadata is None:
            return False
        return metadata.pattern_name.strip().lower() == CASE_HARDENED_PATTERN_NAME

    def get_case_hardened_seed_candidates(self, item: InventoryItem) -> tuple[str, ...]:
        if not self.is_case_hardened(item):
            return ()
        return CASE_HARDENED_BLUE_GEM_SEEDS.get(item.def_index, ())

    def is_fade(self, item: InventoryItem) -> bool:
        paint_index: str = normalize_paint_index(
            item.attributes.get(PAINT_ATTRIBUTE_ID, "")
        )
        if not paint_index:
            return False

        metadata: SkinMetadata | None = self.lookup_skin_metadata(
            item.def_index, paint_index
        )
        if metadata is None:
            return False
        return metadata.pattern_name.strip().lower() == FADE_PATTERN_NAME

    def get_fade_seed_candidates(self, item: InventoryItem) -> tuple[str, ...]:
        if not self.is_fade(item):
            return ()
        return FADE_FULL_SEEDS.get(item.def_index, ())

    def get_lowest_float_value(self, item: InventoryItem) -> str:
        paint_index: str = normalize_paint_index(
            item.attributes.get(PAINT_ATTRIBUTE_ID, "")
        )
        if not paint_index:
            return ""

        metadata: SkinMetadata | None = self.lookup_skin_metadata(
            item.def_index, paint_index
        )
        if metadata is None or not metadata.min_float:
            return ""
        return offset_min_float_value(metadata.min_float, FLOAT_NORMALIZATION_OFFSET)

    def _load_weapon_names(self) -> None:
        data: object | None = fetch_json(BASE_WEAPONS_URL)
        if not isinstance(data, list):
            return

        for entry in data:
            if not isinstance(entry, dict):
                continue
            def_index: str = normalize_scalar(entry.get("def_index"), "")
            name: str = normalize_scalar(entry.get("name"), "")
            if def_index and name:
                self.weapon_names[def_index] = name

    def _load_skin_names(self) -> None:
        for url in SKIN_API_URLS:
            data: object | None = fetch_json(url)
            if not isinstance(data, list):
                continue

            for entry in data:
                if not isinstance(entry, dict):
                    continue
                paint_index: str = normalize_paint_index(
                    normalize_scalar(entry.get("paint_index"), "")
                )
                weapon = entry.get("weapon") or {}
                weapon_id: str = (
                    normalize_scalar(weapon.get("weapon_id"), "")
                    if isinstance(weapon, dict)
                    else ""
                )
                name: str = skin_name_only(normalize_scalar(entry.get("name"), ""))
                image_url: str = normalize_scalar(entry.get("image"), "")
                if not (paint_index and weapon_id and name):
                    continue

                key: tuple[str, str] = (weapon_id, paint_index)
                pattern = entry.get("pattern") or {}
                pattern_id: str = (
                    normalize_scalar(pattern.get("id"), "")
                    if isinstance(pattern, dict)
                    else ""
                )
                pattern_name: str = (
                    normalize_scalar(pattern.get("name"), "")
                    if isinstance(pattern, dict)
                    else ""
                )
                phase: str = normalize_scalar(entry.get("phase"), "")
                min_float: str = normalize_float_value(entry.get("min_float"))
                max_float: str = normalize_float_value(entry.get("max_float"))
                supports_stattrak = bool(entry.get("stattrak"))
                seed_sensitive: bool = is_seed_sensitive_skin(
                    pattern_name=pattern_name,
                    pattern_id=pattern_id,
                    phase=phase,
                )
                existing: SkinMetadata | None = self.skin_metadata.get(key)
                if existing is not None:
                    if not phase:
                        phase = existing.phase
                    if not pattern_name:
                        pattern_name = existing.pattern_name
                    if not pattern_id:
                        pattern_id = existing.pattern_id
                    if not image_url:
                        image_url = existing.image_url
                    if not min_float:
                        min_float = existing.min_float
                    if not max_float:
                        max_float = existing.max_float
                    seed_sensitive = existing.seed_sensitive or seed_sensitive
                    supports_stattrak = existing.supports_stattrak or supports_stattrak

                self.skin_names[key] = name
                self.skin_metadata[key] = SkinMetadata(
                    name=name,
                    phase=phase,
                    pattern_name=pattern_name,
                    pattern_id=pattern_id,
                    image_url=image_url,
                    min_float=min_float,
                    max_float=max_float,
                    seed_sensitive=seed_sensitive,
                    supports_stattrak=supports_stattrak,
                )


def fetch_json(url: str) -> object | None:
    LOGGER.debug("Fetching JSON catalog data from %s", url)
    request = Request(url, headers={"User-Agent": "csgo-gc-skin-finalizer/1.0"})
    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
            LOGGER.debug("Fetched JSON catalog data from %s", url)
            return payload
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        LOGGER.warning("Failed to fetch JSON catalog data from %s: %s", url, exc)
        return None
