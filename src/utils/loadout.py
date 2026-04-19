from __future__ import annotations

from collections import OrderedDict

from .catalog import CatalogResolver
from .constants import CT_CLASS_ID, DEF_INDEX_LOADOUTS, LOADOUT_LABELS, T_CLASS_ID
from .models import (
    DefaultEquip,
    FinalizeStats,
    InventoryDocument,
    InventoryItem,
    LoadoutChoice,
)
from .runtime import LOGGER


def iter_loadout_labels_by_side() -> list[tuple[tuple[str, str], str]]:
    ordered_pairs: list[tuple[tuple[str, str], str]] = []
    for class_id in (T_CLASS_ID, CT_CLASS_ID):
        for pair, label in LOADOUT_LABELS.items():
            if pair[0] == class_id:
                ordered_pairs.append((pair, label))
    return ordered_pairs


def collect_loadout_choices(document: InventoryDocument) -> list[LoadoutChoice]:
    candidates_by_pair: OrderedDict[tuple[str, str], list[InventoryItem]] = OrderedDict(
        (pair, []) for pair in LOADOUT_LABELS
    )
    current_by_pair: dict[tuple[str, str], list[InventoryItem]] = {}

    for item in document.items:
        for pair in DEF_INDEX_LOADOUTS.get(item.def_index, []):
            candidates_by_pair[pair].append(item)

        for class_id, slot_id in item.equipped_state.items():
            pair = (class_id, slot_id)
            current_by_pair.setdefault(pair, []).append(item)

    choices: list[LoadoutChoice] = []
    for pair, label in iter_loadout_labels_by_side():
        candidates = candidates_by_pair.get(pair, [])
        if not candidates:
            continue

        current = next(
            (item for item in current_by_pair.get(pair, []) if item in candidates), None
        )
        choices.append(
            LoadoutChoice(
                pair=pair,
                label=label,
                candidates=candidates,
                current=current,
                default_item=current or candidates[0],
            )
        )

    LOGGER.info("Collected %d loadout choices from inventory", len(choices))
    return choices


def select_loadout_items(
    choices: list[LoadoutChoice],
    resolver: CatalogResolver,
    non_interactive: bool,
    stats: FinalizeStats,
) -> OrderedDict[tuple[str, str], InventoryItem]:
    from ..gui import GuiUnavailableError, prompt_for_choices_gui

    LOGGER.info(
        "Selecting loadout items for %d choices (%s mode)",
        len(choices),
        "non-interactive" if non_interactive else "interactive",
    )
    selected_by_pair: OrderedDict[tuple[str, str], InventoryItem] = OrderedDict()
    ambiguous_choices: list[LoadoutChoice] = []

    for choice in choices:
        if len(choice.candidates) == 1 or non_interactive:
            selected_by_pair[choice.pair] = choice.default_item
            stats.auto_equips += 1
            LOGGER.info(
                "[auto] %s: %s",
                choice.label,
                resolver.describe_item(choice.default_item),
            )
            continue

        selected_by_pair[choice.pair] = choice.default_item
        ambiguous_choices.append(choice)

    if not non_interactive and ambiguous_choices:
        LOGGER.info(
            "Opening GUI for %d ambiguous loadout choices", len(ambiguous_choices)
        )
        try:
            selected_by_pair = OrderedDict(
                prompt_for_choices_gui(
                    all_choices=choices,
                    initial_selected_by_pair=selected_by_pair,
                    ambiguous_choices=ambiguous_choices,
                    resolver=resolver,
                )
            )
            stats.prompted_equips += len(ambiguous_choices)
        except GuiUnavailableError as exc:
            LOGGER.warning(
                "GUI unavailable (%s); falling back to terminal prompts.", exc
            )
            for choice in ambiguous_choices:
                selected = prompt_for_choice(
                    choice.label, choice.candidates, choice.current, resolver
                )
                if selected is None:
                    selected_by_pair.pop(choice.pair, None)
                    LOGGER.info(
                        "%s left unchanged during terminal selection", choice.label
                    )
                else:
                    selected_by_pair[choice.pair] = selected
                    LOGGER.info(
                        "%s selected via terminal prompt: %s",
                        choice.label,
                        resolver.describe_item(selected),
                    )
                stats.prompted_equips += 1

    return selected_by_pair


def rebuild_equips(
    document: InventoryDocument,
    resolver: CatalogResolver,
    non_interactive: bool,
    stats: FinalizeStats,
    rebuild_default_equips: bool,
) -> None:
    LOGGER.info("Rebuilding equipped state and default equips")
    choices = collect_loadout_choices(document)
    selected_by_pair = select_loadout_items(choices, resolver, non_interactive, stats)
    apply_selected_equips(
        document,
        selected_by_pair,
        rebuild_default_equips=rebuild_default_equips,
    )


def apply_selected_equips(
    document: InventoryDocument,
    selected_by_pair: OrderedDict[tuple[str, str], InventoryItem],
    *,
    rebuild_default_equips: bool,
) -> None:
    LOGGER.info("Applying %d selected loadout entries", len(selected_by_pair))

    managed_pairs = set(selected_by_pair)
    for item in document.items:
        preserved: OrderedDict[str, str] = OrderedDict()
        for class_id, slot_id in item.equipped_state.items():
            if (class_id, slot_id) not in managed_pairs:
                preserved[class_id] = slot_id
        item.equipped_state = preserved

    for pair, item in selected_by_pair.items():
        class_id, slot_id = pair
        item.equipped_state[class_id] = slot_id

    if not managed_pairs or not rebuild_default_equips:
        return

    existing_by_pair = {
        (equip.class_id, equip.slot_id): equip for equip in document.default_equips
    }
    rebuilt_default_equips: list[DefaultEquip] = []
    for pair, item in selected_by_pair.items():
        class_id, slot_id = pair
        existing = existing_by_pair.get(pair)
        rebuilt_default_equips.append(
            DefaultEquip(
                def_index=item.def_index,
                class_id=class_id,
                slot_id=slot_id,
                extra_fields=(
                    existing.extra_fields.copy()
                    if existing is not None
                    else OrderedDict()
                ),
            )
        )

    for equip in document.default_equips:
        if (equip.class_id, equip.slot_id) in managed_pairs:
            continue
        rebuilt_default_equips.append(equip)

    document.default_equips = rebuilt_default_equips
    LOGGER.info(
        "Rebuilt default_equips with %d managed entries",
        len(rebuilt_default_equips),
    )


def prompt_for_choice(
    label: str,
    candidates: list[InventoryItem],
    current: InventoryItem | None,
    resolver: CatalogResolver,
) -> InventoryItem | None:
    LOGGER.info(
        "Prompting in terminal for %s with %d candidates", label, len(candidates)
    )
    print(f"\n{label} has {len(candidates)} candidates:")
    print("-" * len(f"\n{label} has {len(candidates)} candidates:"))
    default_index = 1
    for index, item in enumerate(candidates, start=1):
        marker = ""
        if item is current:
            default_index = index
            marker = " [currently equipped]"
        print(f"  {index}. {resolver.describe_item(item)}{marker}")
        print("-" * len(f"  {index}. {resolver.describe_item(item)}{marker}"))

    while True:
        response = (
            input(
                f"Select {label} [1-{len(candidates)}, Enter={default_index}, s=skip]: "
            )
            .strip()
            .lower()
        )
        if not response:
            selection = candidates[default_index - 1]
            LOGGER.info(
                "%s accepted default choice %s",
                label,
                resolver.describe_item(selection),
            )
            return selection
        if response in {"s", "skip"}:
            LOGGER.info("%s skipped during terminal prompt", label)
            return None
        if response.isdigit():
            chosen_index = int(response)
            if 1 <= chosen_index <= len(candidates):
                selection = candidates[chosen_index - 1]
                LOGGER.info(
                    "%s selected via terminal prompt: %s",
                    label,
                    resolver.describe_item(selection),
                )
                return selection
        print("Invalid selection.")
        LOGGER.warning("Invalid terminal selection received for %s", label)
