#!/usr/bin/env python3
import importlib.util
import json
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "enable-cloudflare-config.py"
spec = importlib.util.spec_from_file_location("enable_cloudflare_config", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


class EnableCloudflareTests(unittest.TestCase):
    def test_keeps_reader_and_card_processing(self):
        cfg = {
            "READER": {"backend": "usb", "device": "/dev/input/event7", "nameContains": "SDZNKJLTD USB Reader"},
            "CARD_PROCESSING": {"FORMAT": "HEX10", "BYTE_ORDER": "REVERSED"},
            "CLOUDFLARE": {"enabled": False, "token": ""},
            "DATA_URL": "https://script.google.com/macros/s/old/exec",
        }
        out = mod.merge_cloudflare(
            json.loads(json.dumps(cfg)),
            api_url="https://vkc-kiosk.muddy-rice-38d4.workers.dev",
            token="secret-token",
            kiosk_id="reception",
            kiosk_url="",
            timeout_seconds=5,
        )
        self.assertEqual(out["READER"], cfg["READER"])
        self.assertEqual(out["CARD_PROCESSING"], cfg["CARD_PROCESSING"])
        self.assertEqual(out["DATA_URL"], cfg["DATA_URL"])
        self.assertTrue(out["CLOUDFLARE"]["enabled"])
        self.assertEqual(out["CLOUDFLARE"]["adminToken"], "")
        self.assertEqual(out["CLOUDFLARE"]["token"], "secret-token")

    def test_reuses_existing_token(self):
        cfg = {"CLOUDFLARE": {"token": "already-there"}, "READER": {"backend": "evdev"}}
        out = mod.merge_cloudflare(
            cfg,
            api_url="https://example.workers.dev",
            token=None,
            kiosk_id="reception",
            kiosk_url="",
            timeout_seconds=5,
        )
        self.assertEqual(out["CLOUDFLARE"]["token"], "already-there")
        self.assertEqual(out["READER"]["backend"], "evdev")

    def test_rejects_placeholder_token(self):
        with self.assertRaises(SystemExit):
            mod.merge_cloudflare(
                {"CLOUDFLARE": {"token": "REPLACE_ME_KIOSK_TOKEN"}},
                api_url="https://example.workers.dev",
                token=None,
                kiosk_id="reception",
                kiosk_url="",
                timeout_seconds=5,
            )


if __name__ == "__main__":
    unittest.main()
