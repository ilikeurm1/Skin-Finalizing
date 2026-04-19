from __future__ import annotations

from decimal import Decimal, InvalidOperation
import sys

from .constants import (
    SEED_SENSITIVE_PATTERN_ID_PREFIXES,
    SEED_SENSITIVE_PATTERN_NAMES,
    SEED_SENSITIVE_PATTERN_NAME_SUFFIXES,
)


def strip_wear_suffix(name: str) -> str:
    if not name:
        return name

    lower = name.lower()
    suffixes = (
        " (factory new)",
        " (minimal wear)",
        " (field-tested)",
        " (well-worn)",
        " (battle-scarred)",
    )
    for suffix in suffixes:
        if lower.endswith(suffix):
            name = name[: -len(suffix)].strip()
            break
    return name.strip().lstrip("★ ")


def skin_name_only(name: str) -> str:
    cleaned = strip_wear_suffix(name)
    if "|" in cleaned:
        return cleaned.split("|", 1)[1].strip()
    return cleaned


def normalize_pattern_seed(value: str) -> str:
    if not value:
        return ""

    trimmed = value.strip()
    try:
        numeric = float(trimmed)
    except ValueError:
        return trimmed

    if numeric.is_integer():
        return str(int(numeric))
    return trimmed


def is_seed_sensitive_skin(pattern_name: str, pattern_id: str, phase: str) -> bool:
    if phase.strip():
        return True

    normalized_pattern_id = pattern_id.strip().lower()
    if normalized_pattern_id.startswith(SEED_SENSITIVE_PATTERN_ID_PREFIXES):
        return True

    normalized_pattern_name = pattern_name.strip().lower()
    if not normalized_pattern_name:
        return False

    if normalized_pattern_name in SEED_SENSITIVE_PATTERN_NAMES:
        return True

    return normalized_pattern_name.endswith(SEED_SENSITIVE_PATTERN_NAME_SUFFIXES)


def normalize_scalar(value: object, fallback: str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    return fallback


def normalize_float_value(
    value: object,
    fallback: str = "",
    *,
    snap_to_cent: bool = False,
) -> str:
    normalized = normalize_scalar(value, fallback).strip()
    if not normalized:
        return fallback

    try:
        decimal_value = Decimal(normalized)
    except InvalidOperation:
        return normalized

    if snap_to_cent:
        snapped_value = decimal_value.quantize(Decimal("0.01"))
        if abs(decimal_value - snapped_value) <= Decimal("0.000001"):
            decimal_value = snapped_value

    formatted = format(decimal_value.normalize(), "f")
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted or "0"


def offset_min_float_value(value: object, offset: str) -> str:
    normalized = normalize_float_value(value)
    offset_normalized = normalize_float_value(offset, offset)
    if not normalized:
        return offset_normalized

    try:
        decimal_value = Decimal(normalized)
        offset_value = Decimal(offset_normalized)
    except InvalidOperation:
        return normalized

    snapped_value = decimal_value.quantize(Decimal("0.01"))
    if abs(decimal_value - snapped_value) <= Decimal("0.000001"):
        decimal_value = snapped_value

    adjusted_value = decimal_value + offset_value
    formatted = format(adjusted_value.normalize(), "f")
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted or "0"


def normalize_paint_index(value: str) -> str:
    if not value:
        return ""

    trimmed = value.strip()
    if trimmed.endswith(".000000"):
        return trimmed[:-7]
    if trimmed.endswith(".0"):
        return trimmed[:-2]
    return trimmed


def truncate_text(value: str, limit: int = 68) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def format_key(key: str, indent_level: int) -> str:
    return indent(indent_level) + quote(key)


def format_pair(key: str, value: str, indent_level: int) -> str:
    return indent(indent_level) + f"{quote(key)}\t\t{quote(value)}"


def indent(level: int) -> str:
    return "\t" * level


def quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def safe_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return sys.maxsize
