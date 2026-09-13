#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from card_convert import convert_card_id, normalize_hex_uid


class ConvertTests(unittest.TestCase):
    def test_yarogntec_example(self):
        self.assertEqual(
            convert_card_id(
                "00000055984065",
                card_format="HEX10",
                byte_order="REVERSED",
                nibble_order="REVERSED",
                hex_uid_chars=8,
            ),
            "1443137877",
        )

    def test_dec10_pads(self):
        self.assertEqual(
            convert_card_id("123", card_format="DEC10", decimal_pad_length=10),
            "0000000123",
        )

    def test_normalize_strips_reader_padding(self):
        self.assertEqual(normalize_hex_uid("00000055984065", 8), "55984065")


if __name__ == "__main__":
    unittest.main()
