import asyncio
import logging
from typing import Any

import gi

from .metric import Gth

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # type: ignore

GTH_UUID = "0000ec88-0000-1000-8000-00805f9b34fb"


log = logging.getLogger(__name__)


def set_power(adapter_proxy, on=True):
    adapter_proxy.Set(  # type: ignore
        "(ssv)", "org.bluez.Adapter1", "Powered", GLib.Variant.new_boolean(on)
    )


async def set_discovery(adapter_proxy, on=True) -> bool:
    method = "StartDiscovery" if on else "StopDiscovery"
    try:
        await adapter_proxy.call(method, None, Gio.DBusCallFlags.NO_AUTO_START, 5000)  # type: ignore
        return True
    except GLib.Error as error:
        log.warning(f"{method}: {error.message}")
        return False


async def get_property(props_proxy, iface: str, property: str) -> Any:
    try:
        return (
            await props_proxy.call(  # type: ignore
                "Get",
                GLib.Variant("(ss)", (iface, property)),
                Gio.DBusCallFlags.NONE,
                -1,
            )
        ).unpack()[0]
    except GLib.Error as err:
        if not err.matches(Gio.dbus_error_quark(), Gio.DBusError.INVALID_ARGS):
            raise


async def set_property(props_proxy, iface: str, property: str, variant: GLib.Variant):
    return await props_proxy.call(  # type: ignore
        "Set",
        GLib.Variant("(ssv)", (iface, property, variant)),
        Gio.DBusCallFlags.NONE,
        -1,
    )


class GthScanner:
    def __init__(self, alias_mapping: dict[str, str]):
        self.alias_mapping = alias_mapping
        self.queue = asyncio.Queue()

    async def scan_beacons(self, bluetooth_adapter_name: str = "hci0") -> asyncio.Queue:
        self._bluez_object_manager = Gio.DBusObjectManagerClient.new_for_bus_sync(
            Gio.BusType.SYSTEM, Gio.DBusObjectManagerClientFlags.DO_NOT_AUTO_START, "org.bluez", "/", None, None, None
        )
        self._bluez_object_manager.connect("object-added", self._object_added)
        adapters = [object for object in self._bluez_object_manager.get_objects() if object.get_interface("org.bluez.Adapter1")]
        matching_adapters = [adapter for adapter in adapters if adapter.get_object_path().endswith(bluetooth_adapter_name)]

        if not matching_adapters:
            raise RuntimeError(f"No bluez adapters for name {bluetooth_adapter_name} found!")
        adapter = matching_adapters[0]

        adapter_proxy = adapter.get_interface("org.bluez.Adapter1")
        adapter_props_proxy = adapter.get_interface("org.freedesktop.DBus.Properties")
        if not (adapter_proxy and adapter_props_proxy):
            raise RuntimeError("No usable bluez adapters found!")
        log.debug(f"Using adapter {adapter.get_object_path()}")

        # Reset Adapter
        await set_property(adapter_props_proxy, "org.bluez.Adapter1", "Powered", GLib.Variant.new_boolean(False))
        await set_property(adapter_props_proxy, "org.bluez.Adapter1", "Powered", GLib.Variant.new_boolean(True))

        self._adapter_proxy = adapter_proxy
        self._adapter_props_proxy = adapter_props_proxy
        if await get_property(adapter_props_proxy, "org.bluez.Adapter1", "Discovering"):
            await set_discovery(adapter_proxy, False)
        try:
            await adapter_proxy.call(  # type: ignore
                "SetDiscoveryFilter",
                GLib.Variant("(a{sv})", ({"UUIDs": GLib.Variant("as", [GTH_UUID])},)),
                Gio.DBusCallFlags.NONE,
                -1,
            )
        except GLib.Error as err:
            raise RuntimeError(f"Failed to SetDiscoveryFilter: {err}")

        await set_discovery(adapter_proxy, True)
        return self.queue  # FIXME, use closure

    def _object_added(self, __adapter__, dbus_object: Gio.DBusObject):
        if dbus_object.get_interface("org.bluez.Device1") and (props_proxy := dbus_object.get_interface("org.freedesktop.DBus.Properties")):
            props_proxy = dbus_object.get_interface("org.freedesktop.DBus.Properties")

            async def handle_properties():
                address = await get_property(props_proxy, "org.bluez.Device1", "Address")
                alias = await get_property(props_proxy, "org.bluez.Device1", "Alias")
                if (new_alias := self.alias_mapping.get(address)) and (new_alias != alias):
                    alias = new_alias
                    await props_proxy.call(  # type: ignore
                        "Set",
                        GLib.Variant(
                            "(ssv)",
                            (  # type:ignore
                                "org.bluez.Device1",
                                "Alias",
                                GLib.Variant.new_string(new_alias),
                            ),
                        ),
                        Gio.DBusCallFlags.NONE,
                        -1,
                    )

                uuids = await get_property(props_proxy, "org.bluez.Device1", "UUIDs")
                manufacturer_data = await get_property(props_proxy, "org.bluez.Device1", "ManufacturerData")
                rssi = await get_property(props_proxy, "org.bluez.Device1", "RSSI")
                if (GTH_UUID in uuids) and (data := manufacturer_data.get(1)) and len(data) >= 6:
                    n = int.from_bytes(data[2:5], "big", signed=True)
                    temp = n // 1000 / 10
                    hum = n % 1000 / 10
                    batt = int(data[5] & 0x7F)
                    err = bool(data[5] & 0x80)
                    if not err:
                        self.queue.put_nowait(Gth(alias, address, rssi, temp, hum, batt))

            return asyncio.create_task(handle_properties())
