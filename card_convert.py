"""Ren kort-ID-konvertering (delad mellan app och konfigurationsassistent)."""

from __future__ import annotations

from typing import Any


def normalize_hex_uid(hex_id: str, uid_chars: int) -> str:
    """Behåll äkta ledande 00 i UID; ta bara bort läsarpadding framför."""
    hex_id = "".join(c for c in hex_id.upper() if c in "0123456789ABCDEF")
    if not hex_id:
        return "0" * max(2, uid_chars if uid_chars > 0 else 2)

    if len(hex_id) % 2:
        hex_id = "0" + hex_id

    target = uid_chars if uid_chars > 0 else len(hex_id)
    if target % 2:
        target += 1

    while len(hex_id) > target and hex_id.startswith("00"):
        hex_id = hex_id[2:]

    if len(hex_id) > target:
        hex_id = hex_id[-target:]

    if len(hex_id) < target:
        hex_id = hex_id.zfill(target)

    return hex_id


def convert_card_id(
    raw_card_id: str,
    *,
    card_format: str = "DEC10",
    byte_order: str = "NORMAL",
    nibble_order: str = "NORMAL",
    hex_uid_chars: int = 8,
    decimal_pad_length: int = 10,
) -> str:
    """Konvertera rå läsardata enligt angiven kortkonfiguration."""
    card_format = str(card_format or "DEC10").upper()
    byte_order = str(byte_order or "NORMAL").upper()
    nibble_order = str(nibble_order or "NORMAL").upper()
    card_id = raw_card_id.strip().replace(":", "").replace("-", "").upper()

    if card_format == "DEC10":
        if card_id.isdigit() and len(card_id) < int(decimal_pad_length):
            card_id = card_id.zfill(int(decimal_pad_length))
        return card_id

    if card_format == "HEX10":
        hex_id = normalize_hex_uid(card_id, int(hex_uid_chars))

        if nibble_order in {"REVERSED", "SWAP", "SWAPPED"}:
            hex_id = "".join(hex_id[i + 1] + hex_id[i] for i in range(0, len(hex_id), 2))

        if byte_order == "REVERSED":
            bytes_list = [hex_id[i : i + 2] for i in range(0, len(hex_id), 2)]
            bytes_list.reverse()
            hex_id = "".join(bytes_list)

        try:
            return str(int(hex_id, 16))
        except ValueError:
            return raw_card_id

    return raw_card_id


def conversion_candidates(raw_card_id: str) -> list[dict[str, Any]]:
    """Alla rimliga FORMAT/BYTE/NIBBLE/hexUidChars-kombinationer för en råsträng."""
    combos: list[dict[str, Any]] = []
    seen: set[tuple] = set()

    for card_format in ("DEC10", "HEX10"):
        byte_orders = ("NORMAL", "REVERSED") if card_format == "HEX10" else ("NORMAL",)
        nibble_orders = ("NORMAL", "REVERSED") if card_format == "HEX10" else ("NORMAL",)
        uid_chars_list = (8, 10, 14) if card_format == "HEX10" else (8,)

        for byte_order in byte_orders:
            for nibble_order in nibble_orders:
                for hex_uid_chars in uid_chars_list:
                    key = (card_format, byte_order, nibble_order, hex_uid_chars)
                    if key in seen:
                        continue
                    seen.add(key)
                    converted = convert_card_id(
                        raw_card_id,
                        card_format=card_format,
                        byte_order=byte_order,
                        nibble_order=nibble_order,
                        hex_uid_chars=hex_uid_chars,
                    )
                    combos.append(
                        {
                            "FORMAT": card_format,
                            "BYTE_ORDER": byte_order,
                            "NIBBLE_ORDER": nibble_order,
                            "hexUidChars": hex_uid_chars,
                            "converted": converted,
                            "length": len(converted),
                            "is_digits": converted.isdigit(),
                        }
                    )
    return combos


def card_processing_from_candidate(candidate: dict[str, Any], existing: dict | None = None) -> dict:
    """Bygg CARD_PROCESSING-dict från en kandidat, behåll övriga fält."""
    out = dict(existing or {})
    out["FORMAT"] = candidate["FORMAT"]
    out["BYTE_ORDER"] = candidate["BYTE_ORDER"]
    out["NIBBLE_ORDER"] = candidate["NIBBLE_ORDER"]
    out["hexUidChars"] = int(candidate["hexUidChars"])
    out.setdefault("minIdLength", 5)
    out.setdefault("maxIdLength", 10)
    out.setdefault("decimalPadLength", 10)
    return out
