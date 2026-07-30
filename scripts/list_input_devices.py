#!/usr/bin/env python3
"""Lista tillgängliga input-enheter (för att hitta kortläsarens event-nod)."""

from __future__ import annotations

try:
    from evdev import InputDevice, list_devices
except ImportError:
    raise SystemExit("Saknar evdev. Kör: pip install evdev")


def main() -> int:
    devices = sorted(list_devices())
    if not devices:
        print("Inga /dev/input/event*-enheter hittades.")
        return 1

    print(f"{'PATH':<22} {'NAME'}")
    print("-" * 60)
    for path in devices:
        try:
            dev = InputDevice(path)
            print(f"{path:<22} {dev.name}")
        except OSError as exc:
            print(f"{path:<22} (kunde inte öppnas: {exc})")
    print()
    print("Sätt READER.device i config.json till rätt path,")
    print("eller READER.nameContains till en unik del av namnet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
