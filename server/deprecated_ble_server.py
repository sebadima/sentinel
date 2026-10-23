#!/usr/bin/env python3

import json

import dbus
import dbus.mainloop.glib
import dbus.service
import requests
from gi.repository import GLib

# ============================================================
# BLUEZ
# ============================================================

BLUEZ_SERVICE_NAME = "org.bluez"

GATT_MANAGER_IFACE = "org.bluez.GattManager1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"

GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"

LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"

DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"


# ============================================================
# SENTINEL BLE
# ============================================================

SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
CHARACTERISTIC_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

BLUEZ_ADAPTER = "/org/bluez/hci0"

DEVICE_NAME = "SENTINEL-RPI4"


# ============================================================
# FLASK
# ============================================================

FLASK_URL = "http://127.0.0.1:5040/ingest/co2"


# ============================================================
# LOG
# ============================================================


def log(message):

    print(f"[BLE] {message}", flush=True)


# ============================================================
# APPLICATION
# ============================================================


class Application(dbus.service.Object):
    PATH_BASE = "/com/sentinel"

    def __init__(self, bus):

        self.path = self.PATH_BASE

        dbus.service.Object.__init__(self, bus, self.path)

        self.services = []

        self.add_service(Service(bus, 0, SERVICE_UUID, True))

    def add_service(self, service):

        self.services.append(service)

    def get_path(self):

        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_OM_IFACE, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):

        response = {}

        for service in self.services:
            response[service.get_path()] = service.get_properties()

            for characteristic in service.characteristics:
                response[characteristic.get_path()] = characteristic.get_properties()

        return response


# ============================================================
# SERVICE
# ============================================================


class Service(dbus.service.Object):
    PATH_BASE = "/com/sentinel/service"

    def __init__(self, bus, index, uuid, primary):

        self.path = self.PATH_BASE + str(index)

        self.bus = bus
        self.uuid = uuid
        self.primary = primary

        self.characteristics = []

        dbus.service.Object.__init__(self, bus, self.path)

        self.add_characteristic(
            Characteristic(
                bus, 0, CHARACTERISTIC_UUID, ["write", "write-without-response"], self
            )
        )

    def add_characteristic(self, characteristic):

        self.characteristics.append(characteristic)

    def get_path(self):

        return dbus.ObjectPath(self.path)

    def get_properties(self):

        return {
            GATT_SERVICE_IFACE: {
                "UUID": self.uuid,
                "Primary": dbus.Boolean(self.primary),
                "Characteristics": dbus.Array(
                    [
                        characteristic.get_path()
                        for characteristic in self.characteristics
                    ],
                    signature="o",
                ),
            }
        }


# ============================================================
# CHARACTERISTIC
# ============================================================


class Characteristic(dbus.service.Object):
    PATH_BASE = "/com/sentinel/service0/char"

    def __init__(self, bus, index, uuid, flags, service):

        self.path = self.PATH_BASE + str(index)

        self.bus = bus
        self.uuid = uuid
        self.flags = flags
        self.service = service

        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):

        return dbus.ObjectPath(self.path)

    def get_properties(self):

        return {
            GATT_CHRC_IFACE: {
                "Service": self.service.get_path(),
                "UUID": self.uuid,
                "Flags": dbus.Array(self.flags, signature="s"),
            }
        }

    # ========================================================
    # BLE WRITE
    # ========================================================

    @dbus.service.method(GATT_CHRC_IFACE, in_signature="aya{sv}")
    def WriteValue(self, value, options):

        try:
            # ------------------------------------------------
            # BYTES -> STRING
            # ------------------------------------------------

            raw = bytes(value)

            text = raw.decode("utf-8", errors="replace").strip()

            log(f"RX: {text}")

            # ------------------------------------------------
            # JSON
            # ------------------------------------------------

            data = json.loads(text)

            if not isinstance(data, dict):
                log("ERROR: payload non è un JSON object")

                return

            # ------------------------------------------------
            # LETTURA DATI
            # ------------------------------------------------

            co2 = data.get("co2")
            temp = data.get("temp")
            hum = data.get("hum")
            msg_id = data.get("msg_id")

            log(f"CO2={co2} TEMP={temp} HUM={hum} MSG_ID={msg_id}")

            # ------------------------------------------------
            # VALIDAZIONE CO2
            # ------------------------------------------------

            if co2 is None:
                log("ERROR: campo 'co2' assente")

                return

            # ------------------------------------------------
            # INOLTRO A FLASK
            # ------------------------------------------------

            log(f"FORWARD -> {FLASK_URL}")

            response = requests.post(FLASK_URL, json=data, timeout=3)

            # ------------------------------------------------
            # RISPOSTA FLASK
            # ------------------------------------------------

            log(f"FLASK HTTP {response.status_code}")

            if response.ok:
                try:
                    flask_response = response.json()

                    log(f"FLASK RESPONSE: {flask_response}")

                except Exception:
                    log(f"FLASK RESPONSE: {response.text}")

            else:
                log(f"FLASK ERROR: {response.text}")

        # ====================================================
        # ERRORI JSON
        # ====================================================

        except json.JSONDecodeError as e:
            log(f"JSON ERROR: {e}")

        # ====================================================
        # ERRORE HTTP
        # ====================================================

        except requests.RequestException as e:
            log(f"FLASK CONNECTION ERROR: {e}")

        # ====================================================
        # QUALSIASI ALTRO ERRORE
        # ====================================================

        except Exception as e:
            log(f"ERROR: {type(e).__name__}: {e}")


# ============================================================
# ADVERTISEMENT
# ============================================================


class Advertisement(dbus.service.Object):
    PATH_BASE = "/com/sentinel/advertisement"

    def __init__(self, bus, index):

        self.path = self.PATH_BASE + str(index)

        self.bus = bus

        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):

        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="ss", out_signature="v")
    def Get(self, interface, property):

        if interface != LE_ADVERTISEMENT_IFACE:
            raise dbus.exceptions.DBusException("Invalid interface")

        properties = self.get_properties()

        return properties[property]

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):

        if interface != LE_ADVERTISEMENT_IFACE:
            return {}

        return self.get_properties()

    def get_properties(self):

        return {
            "Type": "peripheral",
            "LocalName": DEVICE_NAME,
            "ServiceUUIDs": [SERVICE_UUID],
        }


# ============================================================
# MAIN
# ============================================================


def main():

    # --------------------------------------------------------
    # GLIB / DBUS
    # --------------------------------------------------------

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    bus = dbus.SystemBus()

    # --------------------------------------------------------
    # ADAPTER
    # --------------------------------------------------------

    adapter = bus.get_object(BLUEZ_SERVICE_NAME, BLUEZ_ADAPTER)

    properties = dbus.Interface(adapter, DBUS_PROP_IFACE)

    properties.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))

    # --------------------------------------------------------
    # APPLICATION
    # --------------------------------------------------------

    application = Application(bus)

    # --------------------------------------------------------
    # ADVERTISEMENT
    # --------------------------------------------------------

    advertisement = Advertisement(bus, 0)

    # --------------------------------------------------------
    # BLUEZ INTERFACES
    # --------------------------------------------------------

    gatt_manager = dbus.Interface(adapter, GATT_MANAGER_IFACE)

    advertising_manager = dbus.Interface(adapter, LE_ADVERTISING_MANAGER_IFACE)

    # --------------------------------------------------------
    # REGISTER GATT
    # --------------------------------------------------------

    log("Registrazione GATT application...")

    gatt_manager.RegisterApplication(
        application.get_path(),
        {},
        reply_handler=lambda: log("GATT application registrata"),
        error_handler=lambda error: log(f"GATT ERROR: {error}"),
    )

    # --------------------------------------------------------
    # REGISTER ADVERTISEMENT
    # --------------------------------------------------------

    log("Registrazione advertising...")

    advertising_manager.RegisterAdvertisement(
        advertisement.get_path(),
        {},
        reply_handler=lambda: log("Advertising attivo"),
        error_handler=lambda error: log(f"ADVERTISING ERROR: {error}"),
    )

    # --------------------------------------------------------
    # STATUS
    # --------------------------------------------------------

    log("RPi4 GATT server pronto")

    log(f"DEVICE = {DEVICE_NAME}")

    log(f"SERVICE = {SERVICE_UUID}")

    log(f"CHARACTERISTIC = {CHARACTERISTIC_UUID}")

    log(f"FLASK = {FLASK_URL}")

    # --------------------------------------------------------
    # MAIN LOOP
    # --------------------------------------------------------

    GLib.MainLoop().run()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
