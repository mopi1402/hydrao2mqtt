import time
from argparse import ArgumentParser
import os
import json
from datetime import datetime
from logger import logger
import logging

from bluepy import btle
import paho.mqtt.client as mqtt

# Credits: https://itnext.io/ble-and-gatt-for-iot-2ae658baafd5


logger = logging.getLogger(__name__)

def print_peripheral(peripheral):
    print("Discovering Services...")
    services = peripheral.getServices()  # a first discovery is necessary apparently
    for service in services:
        print(f"{service} (uuid {service.uuid})")
        for characteristic in service.getCharacteristics():
            print(f"  {characteristic}")
            print(f"    Characteristic id {characteristic.getHandle()}, uuid {characteristic.uuid}. Properties: {characteristic.propertiesToString()}")
            if characteristic.supportsRead():
                print(f"    Value: {characteristic.read()}")

def main():

    # HASSIO ADDON
    logger.info("~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
    logger.info("~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
    logger.info("~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
    logger.info("STARTING HYDRAO2MQTT")
    logger.info("Detecting environnement......")

    HYDRAO_MAC_ADDRESS = ""
    MQTT_HOST = "localhost"
    MQTT_PORT = 1883
    MQTT_USER = ""
    MQTT_PASSWORD = ""
    MQTT_SSL = False

    data_options_path = "/data/options.json"

    try:
        with open(data_options_path) as f:
            logger.info(
                f"{data_options_path} detected ! Hassio Addons Environnement : parsing `options.json`...."
            )
            try:
                data = json.load(f)
                logger.debug(data)

                if data["HYDRAO_MAC_ADDRESS"] != "":
                    HYDRAO_MAC_ADDRESS = data["HYDRAO_MAC_ADDRESS"]
                else:
                    logger.error("No Hydrao Mac address set")
                    exit()

                # CREDENTIALS MQTT
                if data["MQTT_HOST"] != "localhost":
                    MQTT_HOST = data["MQTT_HOST"]

                if data["MQTT_USER"] != "":
                    MQTT_USER = data["MQTT_USER"]

                if data["MQTT_PASSWORD"] != "":
                    MQTT_PASSWORD = data["MQTT_PASSWORD"]

                if data["MQTT_PORT"] != 1883:
                    MQTT_PORT = data["MQTT_PORT"]

                if (data["MQTT_SSL"] == "true") or (data["MQTT_SSL"]):
                    MQTT_SSL = True

            except Exception as e:
                logger.error("Parsing error %s", e)

    except FileNotFoundError:
        logger.info(
            f"No '{data_options_path}', seems we are not in hassio addon mode.")
        HYDRAO_MAC_ADDRESS = os.getenv("HYDRAO_MAC_ADDRESS")
        
        # CREDENTIALS MQTT
        MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
        MQTT_USER = os.getenv("MQTT_USER", "")
        MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
        # 1883 #1884 for websocket without SSL
        MQTT_PORT = os.getenv("MQTT_PORT", 1883)

    logger.info( f"Hydrao declared as {HYDRAO_MAC_ADDRESS}")

    logger.info("~~~~~~~~~~~~~~~~~~~~~~~~~~~~")

    mqtt_client = build_mqtt_client(MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASSWORD)
    backoff = 1
    while True:
        try:
            connect_and_read(mqtt_client, HYDRAO_MAC_ADDRESS)
        except btle.BTLEDisconnectError as e:
            logger.info(f" -> Got disconnected, will retry in {backoff}s. reason: {e}")
            time.sleep(backoff)
            backoff = min(backoff + 1, 30)

def build_mqtt_client(host, port, user, password):
    logger.info("Connecting to MQTT client...")
    client = mqtt.Client()

    if user is not None and password is not None:
        client.username_pw_set(user, password)
    client.connect(host, port, 60)
    client.loop_start()
    logger.info(" -> Connected")
    return client

def mqtt_declare_hydrao_sensors(mqtt_client, hydrao, delete_first=False):
    """
    Declare hydrao sensors in home assistant.
    According to documentation, one can declare multiple sensors sharing the same
    state_topic to allow to update all sensors in one message.
    For now, topics are completely hardcoded
    """
    prefix_topic = f"homeassistant/sensor/hydrao_{hydrao.addr.replace(':', '_')}"
    config_topic = f"{prefix_topic}/config"
    attributes_topic = f"{prefix_topic}/attributes"
    state_topic = f"{prefix_topic}/state"
    config = {
        "name": f"Hydrao shower head {hydrao.addr}",
        "state_class": "total_increasing",
        "device_class": "gas",
        "state_topic": state_topic,
        "unit_of_measurement": "L",
        "expire_after": 60,
        "device": {
            "manufacturer": "hydrao",
            "connections": [["mac", hydrao.addr]]
        },
        "unique_id": hydrao.addr,
        "json_attributes_topic": attributes_topic
    }

    if delete_first:
        mqtt_client.publish(config_topic, '')

    mqtt_client.publish(config_topic, json.dumps(config))

def mqtt_update_hydrao_sensors(mqtt_client, current_volume, total_volume, hydrao):
    prefix_topic = f"homeassistant/sensor/hydrao_{hydrao.addr.replace(':', '_')}"
    attributes_topic = f"{prefix_topic}/attributes"
    state_topic = f"{prefix_topic}/state"
    logger.info(f"Publish state to {state_topic} with {current_volume}")
    mqtt_client.publish(state_topic, current_volume)
    attributes = { "current_volume": current_volume, "last_400_showers": total_volume }
    logger.info(f"Publish attributes to {attributes_topic} with {attributes}")
    mqtt_client.publish(attributes_topic, json.dumps(attributes))


class FakeService:
    def __init__(self, characteristics):
        self.characteristics = characteristics

    def getCharacteristics(self, id):
        return self.characteristics[id]

class FakeCharacteristic:
    def __init__(self, value):
        self.value = value

    def read(self):
        return self.value

class FakeVolumeCharacteristic(FakeCharacteristic):
    def __init__(self, starting_total_volume):
        self.starting_volume= starting_total_volume
        self.start_time = datetime.now()

    def volumes_to_hexstring(total_volume, current_volume):
        # Take a tuple of (total_volume, current_shower_volume)
        # Return a hexstring of int values as a series of bytes. Order is assumed little endian byte (but not sure)
        # e.g., (217, 3) -> bytearray(b'\xd9\x03\x03\x00') -> b'\xd9\x03\x03\x00'
        # ⚠ I'm not sure this conversion is the exact opposite of get_volumes method
        part1 = total_volume.to_bytes(2, 'little')
        part2 = current_volume.to_bytes(2, 'little')
        return part1 + part2

    def read(self):
        current_volume = int((datetime.now() - self.start_time).total_seconds())
        total_volume = self.starting_volume + current_volume
        return FakeVolumeCharacteristic.volumes_to_hexstring(total_volume, current_volume)


class FakeBTPeripheral:
    def __init__(self, addr, characteristics):
        self.addr = addr
        self.service = FakeService(characteristics)

    def addr(self):
        return self.addr

    def getServiceByUUID(self, ignore_uuid):
        # always return the same service
        return self.service


def connect_and_read(mqtt_client, hydrao_mac_address):
    # get args
    args = get_args()

    logger.info("Connecting to Bluetooth Hydrao device...")

    if args.dry_run:
        characteristics = {
          "0000ca1c-0000-1000-8000-00805f9b34fb": [FakeVolumeCharacteristic(100)]
        }
        hydrao = FakeBTPeripheral(hydrao_mac_address, characteristics)
    else:
        hydrao = btle.Peripheral(hydrao_mac_address)
    logger.info(" -> Connected")
    # print_peripheral(hydrao)
    if mqtt_client is not None:
        mqtt_declare_hydrao_sensors(mqtt_client, hydrao)

    so_called_battery_service_uuid = "0000180f-0000-1000-8000-00805f9b34fb"
    battery_service = hydrao.getServiceByUUID(so_called_battery_service_uuid)

    ca31 = "0000ca31-0000-1000-8000-00805f9b34fb"
    ca32 = "0000ca32-0000-1000-8000-00805f9b34fb"
    ca27 = "0000ca27-0000-1000-8000-00805f9b34fb"
    current_volumes = "0000ca1c-0000-1000-8000-00805f9b34fb"

    while True:
        now = time.asctime(time.gmtime())
        total_volume, current_volume = get_volumes(battery_service.getCharacteristics(current_volumes)[0].read())
        print(f"{now} current_volume: {current_volume}L, total volume: {total_volume}L", flush=True)
        # ca32_value_string = battery_service.getCharacteristics(ca32)[0].read()
        # print(f"{now} ca32: {ca32_value_string}")
        # print_unknown(ca32_value_string)
        if mqtt_client is not None:
            mqtt_update_hydrao_sensors(mqtt_client, current_volume, total_volume, hydrao)
        time.sleep(2)

def print_unknown(string):
    # Take a hexstring of values as a series of bytes
    values = bytearray(string)
    full = int.from_bytes(values, byteorder="little")
    full_big = int.from_bytes(values, byteorder="big")
    beg = int.from_bytes(values[0:1], byteorder="little")
    end = int.from_bytes(values[2:3], byteorder="little")
    print(f"full {full}, full_big: {full_big}, beg {beg}, end {end}")


def get_volumes(volumes_string):
    # Return a tuple of (total_volume, current_shower_volume)
    # take a hexstring of int values as a series of bytes. Order is assumed little endian byte (but not sure)
    # e.g., b'\xd9\x03\x03\x00' -> bytearray(b'\xd9\x03\x03\x00') -> (217, 3)
    combined_value = bytearray(volumes_string)
    total_volume = int.from_bytes(combined_value[0:1], byteorder="little")
    current_shower_volume = int.from_bytes(combined_value[2:3], byteorder="little")
    return (total_volume, current_shower_volume)


def get_args():
    arg_parser = ArgumentParser(description="Hydrao shower head")
    arg_parser.add_argument('--dry_run', help="Activate dry-run mode", action="store_const", const=True)
    args = arg_parser.parse_args()
    return args


if __name__ == "__main__":
    main()
