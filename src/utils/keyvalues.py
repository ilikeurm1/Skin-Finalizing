from __future__ import annotations

from collections import OrderedDict

from .constants import STANDARD_ITEM_FIELDS
from .models import DefaultEquip, InventoryDocument, InventoryItem
from .runtime import LOGGER
from .text import format_key, format_pair, indent, normalize_scalar, safe_int


class KeyValueParseError(RuntimeError):
    pass


def tokenize_keyvalues(text: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    length: int = len(text)

    while index < length:
        ch: str = text[index]

        if ch.isspace():
            index += 1
            continue

        if ch == "/" and index + 1 < length and text[index + 1] == "/":
            index += 2
            while index < length and text[index] != "\n":
                index += 1
            continue

        if ch in "{}":
            tokens.append(ch)
            index += 1
            continue

        if ch == '"':
            index += 1
            buffer: list[str] = []
            while index < length:
                ch = text[index]
                if ch == "\\" and index + 1 < length:
                    next_char: str = text[index + 1]
                    if next_char in {'"', "\\"}:
                        buffer.append(next_char)
                        index += 2
                        continue
                if ch == '"':
                    index += 1
                    break
                buffer.append(ch)
                index += 1
            else:
                raise KeyValueParseError(
                    "Unterminated quoted string in inventory file."
                )

            tokens.append("".join(buffer))
            continue

        start: int = index
        while index < length and not text[index].isspace() and text[index] not in "{}":
            if text[index] == "/" and index + 1 < length and text[index + 1] == "/":
                break
            index += 1
        tokens.append(text[start:index])

    return tokens


def parse_keyvalues(text: str) -> OrderedDict[str, object]:
    tokens: list[str] = tokenize_keyvalues(text)
    parsed, next_index = parse_object(tokens, 0)
    if next_index != len(tokens):
        raise KeyValueParseError("Unexpected trailing tokens in inventory file.")
    return parsed


def parse_object(tokens: list[str], index: int) -> tuple[OrderedDict[str, object], int]:
    result: OrderedDict[str, object] = OrderedDict()

    while index < len(tokens):
        token: str = tokens[index]
        if token == "}":
            return result, index + 1
        if token == "{":
            raise KeyValueParseError("Unexpected '{' in inventory file.")

        key: str = token
        index += 1
        if index >= len(tokens):
            raise KeyValueParseError(f"Missing value for key '{key}'.")

        token = tokens[index]
        if token == "{":
            child, index = parse_object(tokens, index + 1)
            result[key] = child
            continue

        if token == "}":
            raise KeyValueParseError(f"Missing value for key '{key}'.")

        result[key] = token
        index += 1

    return result, index


def parse_inventory_document(text: str) -> InventoryDocument:
    LOGGER.debug("Parsing inventory document with %d characters", len(text))
    parsed: OrderedDict[str, object] = parse_keyvalues(text)
    container: OrderedDict[str, object] = unwrap_root_container(parsed)

    items_object: OrderedDict[str, object]
    other_top_level: OrderedDict[str, object] = OrderedDict()

    if "items" in container and isinstance(container["items"], OrderedDict):
        items_object = container["items"]
        for key, value in container.items():
            if key not in {"items", "default_equips"}:
                other_top_level[key] = value
    elif "Items" in container and isinstance(container["Items"], OrderedDict):
        items_object = container["Items"]
        for key, value in container.items():
            if key not in {"Items", "default_equips"}:
                other_top_level[key] = value
    else:
        items_object = OrderedDict()
        for key, value in container.items():
            if key.isdigit() and isinstance(value, OrderedDict):
                items_object[key] = value
            elif key != "default_equips":
                other_top_level[key] = value

    items: list[InventoryItem] = []
    for item_id, raw_value in items_object.items():
        if not isinstance(raw_value, OrderedDict):
            continue
        items.append(parse_item(item_id, raw_value))
    items.sort(key=lambda item: safe_int(item.id))

    default_equips: list[DefaultEquip] = parse_default_equips(
        container.get("default_equips")
    )
    LOGGER.info(
        "Parsed inventory document with %d items and %d default equips",
        len(items),
        len(default_equips),
    )
    return InventoryDocument(
        items=items, default_equips=default_equips, other_top_level=other_top_level
    )


def unwrap_root_container(parsed: OrderedDict[str, object]) -> OrderedDict[str, object]:
    if len(parsed) != 1:
        return parsed

    only_key, only_value = next(iter(parsed.items()))
    if not isinstance(only_value, OrderedDict):
        return parsed

    if only_key in {"items", "Items", "default_equips"}:
        return parsed

    nested_keys = set(only_value.keys())
    if (
        "items" in nested_keys
        or "Items" in nested_keys
        or any(key.isdigit() for key in nested_keys)
    ):
        return only_value

    return parsed


def parse_item(item_id: str, raw_item: OrderedDict[str, object]) -> InventoryItem:
    attributes: OrderedDict[str, str] = parse_string_map(
        raw_item.get("attributes") or raw_item.get("Attributes")
    )
    equipped_state: OrderedDict[str, str] = parse_string_map(
        raw_item.get("equipped_state") or raw_item.get("EquippedState")
    )

    extra_fields: OrderedDict[str, object] = OrderedDict()
    lowered_standard: set[str] = {field.lower() for field in STANDARD_ITEM_FIELDS}
    for key, value in raw_item.items():
        lowered: str = key.lower()
        if lowered in lowered_standard or lowered in {"attributes", "equipped_state"}:
            continue
        extra_fields[key] = value

    return InventoryItem(
        original_id=item_id,
        id=item_id,
        inventory=normalize_scalar(raw_item.get("inventory"), "0"),
        def_index=normalize_scalar(raw_item.get("def_index"), "0"),
        level=normalize_scalar(raw_item.get("level"), "1"),
        quality=normalize_scalar(raw_item.get("quality"), "0"),
        flags=normalize_scalar(raw_item.get("flags"), "0"),
        origin=normalize_scalar(raw_item.get("origin"), "8"),
        in_use=normalize_scalar(raw_item.get("in_use"), "0"),
        rarity=normalize_scalar(raw_item.get("rarity"), "0"),
        attributes=attributes,
        equipped_state=equipped_state,
        extra_fields=extra_fields,
    )


def parse_string_map(value: object) -> OrderedDict[str, str]:
    if not isinstance(value, OrderedDict):
        return OrderedDict()

    result: OrderedDict[str, str] = OrderedDict()
    for key, raw_value in value.items():
        if isinstance(raw_value, OrderedDict):
            continue
        result[key] = normalize_scalar(raw_value, "")
    return result


def parse_default_equips(value: object) -> list[DefaultEquip]:
    if not isinstance(value, OrderedDict):
        return []

    equips: list[DefaultEquip] = []
    for def_index, raw_entry in value.items():
        if not isinstance(raw_entry, OrderedDict):
            continue
        extra_fields: OrderedDict[str, object] = OrderedDict()
        for key, raw_value in raw_entry.items():
            if key not in {"class_id", "slot_id"}:
                extra_fields[key] = raw_value

        equips.append(
            DefaultEquip(
                def_index=def_index,
                class_id=normalize_scalar(raw_entry.get("class_id"), "0"),
                slot_id=normalize_scalar(raw_entry.get("slot_id"), "0"),
                extra_fields=extra_fields,
            )
        )
    return equips


def serialize_inventory_document(document: InventoryDocument) -> str:
    lines: list[str] = ['"items"', "{"]
    for item in sorted(document.items, key=lambda value: safe_int(value.id)):
        lines.append(format_key(item.id, 1))
        lines.append(indent(1) + "{")
        lines.extend(serialize_item(item, 2))
        lines.append(indent(1) + "}")
    lines.append("}")

    if document.default_equips:
        lines.append('"default_equips"')
        lines.append("{")
        for equip in document.default_equips:
            lines.append(format_key(equip.def_index, 1))
            lines.append(indent(1) + "{")
            equip_object: OrderedDict[str, object] = OrderedDict()
            equip_object["class_id"] = equip.class_id
            equip_object["slot_id"] = equip.slot_id
            for key, value in equip.extra_fields.items():
                equip_object[key] = value
            lines.extend(serialize_kv_object(equip_object, 2))
            lines.append(indent(1) + "}")
        lines.append("}")

    for key, value in document.other_top_level.items():
        if isinstance(value, OrderedDict):
            lines.append(format_key(key, 0))
            lines.append("{")
            lines.extend(serialize_kv_object(value, 1))
            lines.append("}")
        else:
            lines.append(format_pair(key, normalize_scalar(value, ""), 0))

    return "\n".join(lines) + "\n"


def serialize_item(item: InventoryItem, indent_level: int) -> list[str]:
    item_object: OrderedDict[str, object] = OrderedDict()
    item_object["inventory"] = item.inventory
    item_object["def_index"] = item.def_index
    item_object["level"] = item.level
    item_object["quality"] = item.quality
    item_object["flags"] = item.flags
    item_object["origin"] = item.origin
    item_object["in_use"] = item.in_use
    item_object["rarity"] = item.rarity
    for key, value in item.extra_fields.items():
        item_object[key] = value
    if item.attributes:
        item_object["attributes"] = item.attributes
    if item.equipped_state:
        item_object["equipped_state"] = item.equipped_state
    return serialize_kv_object(item_object, indent_level)


def serialize_kv_object(obj: OrderedDict[str, object], indent_level: int) -> list[str]:
    lines: list[str] = []
    for key, value in obj.items():
        if isinstance(value, OrderedDict):
            lines.append(format_key(key, indent_level))
            lines.append(indent(indent_level) + "{")
            lines.extend(serialize_kv_object(value, indent_level + 1))
            lines.append(indent(indent_level) + "}")
        else:
            lines.append(format_pair(key, normalize_scalar(value, ""), indent_level))
    return lines
