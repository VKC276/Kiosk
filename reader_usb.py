"""PyUSB-backend för SDZNKJLTD m.fl. som kraschar xHCI via usbhid på iface 1.

Kerneln ska ha usbhid-quirk IGNORE för VID:PID så iface 1 aldrig proberas.
Denna modul claimar bara interface 0 och läser HID boot-keyboard-rapporter.
"""

from __future__ import annotations

import threading
import time

# USB HID usage → tecken (boot keyboard)
HID_KEYMAP = {
    0x1E: "1", 0x1F: "2", 0x20: "3", 0x21: "4", 0x22: "5",
    0x23: "6", 0x24: "7", 0x25: "8", 0x26: "9", 0x27: "0",
    0x04: "A", 0x05: "B", 0x06: "C", 0x07: "D", 0x08: "E", 0x09: "F",
}
HID_ENTER = {0x28, 0x58}  # Enter, Keypad Enter


def usb_card_reader_thread(vendor_id: int, product_id: int, on_raw_id, should_run=lambda: True):
    """Lyssna på USB-HID iface 0. on_raw_id(str) anropas vid komplett blipp (före Enter)."""
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
        dev = usb.core.find(idVendor=vendor_id, idProduct=product_id)
        if dev is None:
            time.sleep(1.0)
            continue

        try:
            # Detach kernel driver om den trots quirk sitter kvar på iface 0
            try:
                if dev.is_kernel_driver_active(0):
                    dev.detach_kernel_driver(0)
            except (ValueError, NotImplementedError, usb.core.USBError):
                pass

            # Sätt konfiguration om behövs
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
            prev_keys = set()
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
                        if not reading:
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
