"""PyUSB-backend för SDZNKJLTD m.fl. som kraschar xHCI via usbhid på iface 1.

Flöde:
1) udev sätter authorized=0 + driver_override på iface 0/1 (ingen usbhid).
2) Vi sätter authorized=1 via sysfs och claimar ENDAST interface 0 med PyUSB.
"""

from __future__ import annotations

import glob
import time
from pathlib import Path

# USB HID usage → tecken (boot keyboard)
HID_KEYMAP = {
    0x1E: "1", 0x1F: "2", 0x20: "3", 0x21: "4", 0x22: "5",
    0x23: "6", 0x24: "7", 0x25: "8", 0x26: "9", 0x27: "0",
    0x04: "A", 0x05: "B", 0x06: "C", 0x07: "D", 0x08: "E", 0x09: "F",
}
HID_ENTER = {0x28, 0x58}  # Enter, Keypad Enter


def _sysfs_device_dir(vendor_id: int, product_id: int) -> Path | None:
    vend = f"{vendor_id:04x}"
    prod = f"{product_id:04x}"
    for vendor_file in glob.glob("/sys/bus/usb/devices/*/idVendor"):
        path = Path(vendor_file)
        try:
            if path.read_text(encoding="utf-8").strip().lower() != vend:
                continue
            if (path.parent / "idProduct").read_text(encoding="utf-8").strip().lower() != prod:
                continue
            return path.parent
        except OSError:
            continue
    return None


def _authorize_device(vendor_id: int, product_id: int) -> bool:
    """Sätt authorized=1 men behåll driver_override så usbhid inte binder."""
    devdir = _sysfs_device_dir(vendor_id, product_id)
    if not devdir:
        return False

    # Säkerställ override på iface 0/1 innan authorize
    for iface in sorted(devdir.glob(f"{devdir.name}:*.*")):
        num_file = iface / "bInterfaceNumber"
        override = iface / "driver_override"
        if not num_file.is_file() or not override.is_file():
            continue
        try:
            num = num_file.read_text(encoding="utf-8").strip()
            if num in {"0", "1"}:
                override.write_text("do-not-bind", encoding="utf-8")
        except OSError:
            pass

    auth = devdir / "authorized"
    try:
        if auth.is_file():
            auth.write_text("1", encoding="utf-8")
            print(f"USB: authorized=1 på {devdir.name} (driver_override aktiv)")
            return True
    except OSError as exc:
        print(f"USB: kunde inte authorize {devdir}: {exc}")
    return False


def usb_card_reader_thread(vendor_id: int, product_id: int, on_raw_id, should_run=lambda: True):
    """Lyssna på USB-HID iface 0. on_raw_id(str) anropas vid komplett blipp."""
    try:
        import usb.core
        import usb.util
    except ImportError:
        print("KRITISKT FEL: pyusb saknas. Kör: pip install pyusb")
        return

    print(
        f"USB-kortläsartråd startad (pyusb). "
        f"Söker {vendor_id:#06x}:{product_id:#06x}, claimar endast interface 0."
    )

    while should_run():
        # Om udev satt authorized=0: godkänn utan kernel-bind
        _authorize_device(vendor_id, product_id)

        dev = usb.core.find(idVendor=vendor_id, idProduct=product_id)
        if dev is None:
            time.sleep(1.0)
            continue

        try:
            try:
                if dev.is_kernel_driver_active(0):
                    dev.detach_kernel_driver(0)
            except (ValueError, NotImplementedError, usb.core.USBError):
                pass

            try:
                dev.set_configuration()
            except usb.core.USBError:
                pass

            cfg = dev.get_active_configuration()
            intf = cfg[(0, 0)]
            usb.util.claim_interface(dev, intf.bInterfaceNumber)

            ep_in = usb.util.find_descriptor(
                intf,
                custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
                == usb.util.ENDPOINT_IN,
            )
            if ep_in is None:
                print("USB FEL: Ingen IN-endpoint på interface 0.")
                time.sleep(2.0)
                continue

            print(
                f"USB: Ansluten {vendor_id:#06x}:{product_id:#06x} "
                f"ep={ep_in.bEndpointAddress:#04x}. Lyssnar…"
            )

            buf = []
            prev_keys: set[int] = set()
            reading = False

            while should_run():
                try:
                    data = dev.read(ep_in.bEndpointAddress, ep_in.wMaxPacketSize or 8, timeout=500)
                except usb.core.USBTimeoutError:
                    continue
                except usb.core.USBError as exc:
                    print(f"USB: Läsfel ({exc}) — väntar på omanslutning.")
                    break

                if not data or len(data) < 3:
                    continue

                keys = {int(b) for b in data[2:] if b}
                pressed = keys - prev_keys
                prev_keys = keys

                for code in pressed:
                    if code in HID_KEYMAP:
                        reading = True
                        buf.append(HID_KEYMAP[code])
                    elif code in HID_ENTER:
                        if buf:
                            raw = "".join(buf)
                            buf = []
                            reading = False
                            try:
                                on_raw_id(raw)
                            except Exception as exc:
                                print(f"USB: Fel i on_raw_id: {exc}")
                        else:
                            reading = False

        except usb.core.USBError as exc:
            print(f"USB: Enhetsfel ({exc})")
        except Exception as exc:
            print(f"USB: Oväntat fel ({exc})")
        finally:
            try:
                usb.util.dispose_resources(dev)
            except Exception:
                pass
            time.sleep(1.0)
