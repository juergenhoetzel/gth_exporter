import json
import logging
from dataclasses import asdict, dataclass
from typing import Any, Callable

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # type: ignore

GTH_UUID = "0000ec88-0000-1000-8000-00805f9b34fb"


def log_gerror_handler(log_message: str):
    error_handler: Callable[[Any, GLib.Error, Any], None] = lambda __obj__, error, __user_data__: log.warning(
        f"{log_message}: {error.message}"
    )
    return error_handler


log = logging.getLogger(__name__)


@dataclass
class Gth:
    alias: str
    address: str
    rssi: int
    temp_celsius: float
    humidity_percent: float
    battery_percent: int


class GthScanner:
    def __init__(self, alias_mapping: dict[str, str], callback: Callable[[Gth], None] = lambda gth: log.debug(json.dumps(asdict(gth)))):
        self.alias_mapping = alias_mapping
        self.callback = callback

        self._bluez_object_manager = Gio.DBusObjectManagerClient.new_for_bus_sync(
            Gio.BusType.SYSTEM, Gio.DBusObjectManagerClientFlags.DO_NOT_AUTO_START, "org.bluez", "/", None, None, None
        )
        self._bluez_object_manager.connect("object-added", self._object_added)

    def setup_adapter(self, bluetooth_adapter_name: str = "hci0"):
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
        # Turn on Gth scanning
        adapter_proxy.SetDiscoveryFilter(  # type: ignore
            "(a{sv})", {"UUIDs": GLib.Variant("as", [GTH_UUID])}
        )  # type: ignore
        self._adapter_proxy = adapter_proxy
        self._adapter_props_proxy = adapter.get_interface("org.freedesktop.DBus.Properties")
        self.restart_discovery()

    def start_discovery(self):
        assert self._adapter_proxy

        def error_handler(__obj__, error: GLib.Error, __userdata__):
            log.warning(f"Error: {error.message}")

        self._adapter_proxy.StartDiscovery(  # type: ignore
            error_handler=error_handler, result_handler=lambda *__args__: log.debug("Scan enabled")
        )

    def stop_discovery(self, stopped_cb: Callable[[], None]):
        """Stop Disovery ignoring errors"""
        assert self._adapter_proxy
        self._adapter_proxy.StopDiscovery(  # type: ignore
            result_handler=lambda *__args__: stopped_cb()
        )

    def restart_discovery(self):
        self.stop_discovery(self.start_discovery)
        return True

    @staticmethod
    def _parse(props: dict[str, Any]) -> Gth | None:
        "Return tuple Gth metrics for the given device properties"
        if (GTH_UUID in props.get("UUIDs", [])) and (data := props.get("ManufacturerData", {}).get(1)) and len(data) >= 6:
            n = int.from_bytes(data[2:5], "big", signed=True)
            temp = n // 1000 / 10
            hum = n % 1000 / 10
            batt = int(data[5] & 0x7F)
            err = bool(data[5] & 0x80)
            if not err:
                return Gth(props.get("Alias", ""), props.get("Address", ""), props.get("RSSI", 0), temp, hum, batt)

    def _object_added(self, __adapter__, dbus_object: Gio.DBusObject):
        if dbus_object.get_interface("org.bluez.Device1") and (props_proxy := dbus_object.get_interface("org.freedesktop.DBus.Properties")):

            def properties_received(__obj__, all_props: dict, __userdata__):
                address = all_props.get("Address", "")
                if (new_alias := self.alias_mapping.get(address)) and (new_alias != all_props.get("Alias")):
                    all_props["Alias"] = new_alias
                    props_proxy.Set(  # type: ignore
                        "(ssv)",
                        "org.bluez.Device1",
                        "Alias",
                        GLib.Variant.new_string(new_alias),
                        result_handler=lambda *_: log.debug(f"Alias for {address} set to {new_alias}"),
                        error_handler=log_gerror_handler,
                    )  # type: ignore
                if gth := GthScanner._parse(all_props):
                    self.callback(gth)

            props_proxy.GetAll("(s)", "org.bluez.Device1", result_handler=properties_received, error_handler=log_gerror_handler)  # type: ignore
