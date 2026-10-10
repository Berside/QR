import asyncio
from bleak import BleakClient, BleakScanner

from .exception import BLEException
from .logger_config import get_logger

logger = get_logger()


async def find_device(device_name_prefix=None):
    device_name_prefix = 'B31'
    devices = await BleakScanner.discover()
    print("ALL DEVICES", devices)
    for device in devices:
        print("iiii", device.name)
        print("oooo", device_name_prefix)
        if device.name and device.name.lower().startswith(device_name_prefix.lower()):
            return device
    raise BLEException(f"Failed to find device {device_name_prefix}")


async def scan_devices(device_name=None):
    print("Scanning for devices...")
    devices = await BleakScanner.discover()
    for device in devices:
        if device_name:
            if device.name and device_name.lower() in device.name.lower():
                print(f"Found device: {device.name} at {device.address}")
                return device
        else:
            print(f"Found device: {device.name} at {device.address}")
    return None


class BLETransport:
    def __init__(self, device=None):
        self.device = device
        self.client = BleakClient(device) if device is not None else None

    async def __aenter__(self):
        # Automatically connect if address is provided during initialization
        if self.device is not None:
            self.client = BleakClient(self.device)
            if await self.client.connect():
                logger.info(f"Connected to {self.device}")
                return self
            else:
                raise BLEException(f"Failed to connect to the BLE device at {self.device}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.disconnect()
            logger.info("Disconnected.")

    async def connect(self, device):
        if self.client is None or self.device != device:
            self.device = device
            self.client = BleakClient(device)
        if not self.client.is_connected:
            return await self.client.connect()
        return True

    async def disconnect(self):
        if self.client and self.client.is_connected:
            await self.client.disconnect()

    async def write(self, data, char_uuid):
        if self.client and self.client.is_connected:
            await self.client.write_gatt_char(char_uuid, data)
        else:
            raise BLEException("BLE client is not connected.")

    async def start_notification(self, char_uuid, handler):
        if self.client and self.client.is_connected:
            await self.client.start_notify(char_uuid, handler)
        else:
            raise BLEException("BLE client is not connected.")

    async def stop_notification(self, char_uuid):
        if self.client and self.client.is_connected:
            await self.client.stop_notify(char_uuid)
        else:
            raise BLEException("BLE client is not connected.")
