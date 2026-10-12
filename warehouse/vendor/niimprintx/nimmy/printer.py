import enum
import asyncio
import struct
from PIL import Image, ImageOps
from .exception import BLEException, PrinterException
from .bluetooth import BLETransport
from .logger_config import get_logger
from .packet import NiimbotPacket, packet_to_int


logger = get_logger()


class InfoEnum(enum.IntEnum):
    DENSITY = 1
    PRINTSPEED = 2
    LABELTYPE = 3
    LANGUAGETYPE = 6
    AUTOSHUTDOWNTIME = 7
    DEVICETYPE = 8
    SOFTVERSION = 9
    BATTERY = 10
    DEVICESERIAL = 11
    HARDVERSION = 12


class RequestCodeEnum(enum.IntEnum):
    GET_INFO = 64  # 0x40
    GET_RFID = 26  # 0x1A
    HEARTBEAT = 220  # 0xDC
    SET_LABEL_TYPE = 35  # 0x23
    SET_LABEL_DENSITY = 33  # 0x21
    START_PRINT = 1  # 0x01
    END_PRINT = 243  # 0xF3
    START_PAGE_PRINT = 3  # 0x03
    END_PAGE_PRINT = 227  # 0xE3
    ALLOW_PRINT_CLEAR = 32  # 0x20
    SET_DIMENSION = 19  # 0x13
    SET_QUANTITY = 21  # 0x15
    GET_PRINT_STATUS = 163  # 0xA3


class PrinterClient:
    def __init__(self, device):
        self.char_uuid = None
        self.device = device
        self.transport = BLETransport()
        self.notification_event = asyncio.Event()
        self.notification_data = None
        self.expected_responses = set()
        self.notification_buffer = bytearray()
        self.notifications_started = False
        self.printer_error = None

    async def connect(self):
        if await self.transport.connect(self.device):
            if not self.char_uuid:
                await self.find_characteristics()
            if not self.notifications_started:
                await self.transport.start_notification(self.char_uuid, self.notification_handler)
                self.notifications_started = True
            logger.info(f"Successfully connected to {self.device.name}")
            return True
        logger.error("Connection failed.")
        return False

    async def disconnect(self):
        await self.transport.disconnect()
        self.notifications_started = False
        self.notification_buffer.clear()
        self.printer_error = None
        logger.info(f"Printer {self.device.name} disconnected.")

    async def find_characteristics(self):
        services = {}
        for service in self.transport.client.services:
            s = []
            for char in service.characteristics:
                s.append({
                    "id": char.uuid,
                    "handle": char.handle,
                    "properties": char.properties
                })

            services[service.uuid] = s

        for characteristics in services.values():
            for characteristic in characteristics:
                props = characteristic['properties']
                if 'notify' in props and ('write' in props or 'write-without-response' in props):
                    self.char_uuid = characteristic['id']
                    break
            if self.char_uuid:
                break
        if not self.char_uuid:
            raise PrinterException("Cannot find bluetooth characteristics.")

    async def send_command(self, request_code, data, timeout=10):
        if not self.transport.client or not self.transport.client.is_connected:
            if not await self.connect():
                raise BLEException("Cannot connect to printer.")
        self._raise_printer_error()
        # Unsolicited row/status notifications must not acknowledge another command.
        responses = {
            0x1A: {0x1B}, 0xDC: {0xD9, 0xDD, 0xDE, 0xDF},
            0x21: {0x31}, 0x23: {0x33}, 0x01: {0x02}, 0x03: {0x04},
            0x13: {0x14}, 0x15: {0x16}, 0x20: {0x30},
            0xE3: {0xE4}, 0xF3: {0xF4}, 0xA3: {0xB3},
        }
        self.expected_responses = ({0x40 + data[0]} if request_code == 0x40
                                   else responses[request_code])
        self.notification_data = None
        self.notification_event.clear()
        try:
            await self.transport.write(NiimbotPacket(request_code, data).to_bytes(), self.char_uuid)
            await asyncio.wait_for(self.notification_event.wait(), timeout)
            packet = self.notification_data
            if packet.type == 0xDB:
                raise PrinterException(f"Printer error: {packet.data.hex()}")
            return packet
        except asyncio.TimeoutError as exc:
            raise PrinterException(
                f"Timeout waiting for {RequestCodeEnum(request_code).name}"
            ) from exc
        finally:
            self.expected_responses = set()

    async def write_raw(self, data):
        # Reconnecting here would lose the active page; fail instead of losing rows.
        self._raise_printer_error()
        await self.transport.write(data.to_bytes(), self.char_uuid)

    def _raise_printer_error(self):
        if self.printer_error is not None:
            raise PrinterException(f"Printer error: {self.printer_error.hex()}")

    async def write_no_notify(self, request_code, data):
        await self.write_raw(NiimbotPacket(request_code, data))

    def notification_handler(self, sender, data):
        # A notification may contain a partial frame or several complete frames.
        self.notification_buffer.extend(data)
        while len(self.notification_buffer) >= 4:
            if self.notification_buffer[:2] != b"\x55\x55":
                del self.notification_buffer[0]
                continue
            size = self.notification_buffer[3] + 7
            if len(self.notification_buffer) < size:
                return
            frame = bytes(self.notification_buffer[:size])
            del self.notification_buffer[:size]
            try:
                packet = NiimbotPacket.from_bytes(frame)
            except (AssertionError, IndexError):
                logger.warning("Ignoring invalid printer response")
                continue
            if packet.type == 0xDB:
                self.printer_error = packet.data
            if (packet.type in self.expected_responses or packet.type == 0xDB) and not self.notification_event.is_set():
                self.notification_data = packet
                self.notification_event.set()

    async def print_image(self, image: Image, density: int = 3, quantity: int = 1,
                          vertical_offset=0, horizontal_offset=0, timeout=60):
        if not 1 <= quantity <= 65535:
            raise ValueError("Quantity must be between 1 and 65535")
        if not (0 < image.width <= 65535 and 0 < image.height <= 65535):
            raise ValueError("Invalid image dimensions")
        # Offsets move artwork inside the label; never change its physical length.
        image = self._prepare_image(image, vertical_offset, horizontal_offset)
        for operation, method, args in (
            ("density", self.set_label_density, (density,)),
            ("label type", self.set_label_type, (1,)),
            ("print start", self.start_print, ()),
            ("page start", self.start_page_print, ()),
            ("page dimensions", self.set_dimension, (image.height, image.width)),
            ("quantity", self.set_quantity, (quantity,)),
        ):
            if not await method(*args):
                raise PrinterException(f"Printer rejected {operation}")

        for pkt in self._encode_image(image):
            await self.write_raw(pkt)
            await asyncio.sleep(0.01)

        async def finish():
            while not await self.end_page_print():
                await asyncio.sleep(0.1)
            while True:
                status = await self.get_print_status()
                if status['page'] >= quantity:
                    break
                await asyncio.sleep(0.1)
            # A page counter is not an acknowledgement that the job/feed is closed.
            while not await self.end_print():
                await asyncio.sleep(0.1)

        try:
            await asyncio.wait_for(finish(), timeout)
        except asyncio.TimeoutError as exc:
            raise PrinterException("Timed out waiting for print/feed completion") from exc

    @staticmethod
    def _prepare_image(image, vertical_offset=0, horizontal_offset=0):
        canvas = Image.new("RGBA", image.size, "white")
        canvas.alpha_composite(image.convert("RGBA"), (horizontal_offset, vertical_offset))
        return canvas.convert("RGB")

    def _encode_image(self, image: Image, vertical_offset=0, horizontal_offset=0):
        image = self._prepare_image(image, vertical_offset, horizontal_offset)
        img = ImageOps.invert(image.convert("L")).convert("1")
        # Pillow packs each row MSB first and pads its RIGHT edge to a whole byte.
        # int(bit_string).to_bytes() instead pads on the left for widths like 383.
        stride = (img.width + 7) // 8
        bitmap = img.tobytes()
        is_b31 = (self.device.name or "").lower().startswith("b31")
        for y in range(img.height):
            line_data = bitmap[y * stride:(y + 1) * stride]
            counts = (0, 0, 0)
            if is_b31:
                # B31 has 600 head dots: three 200-dot / 25-byte segments.
                counts = tuple(sum(byte.bit_count() for byte in line_data[i:i + 25])
                               for i in (0, 25, 50))
            header = struct.pack(">H3BB", y, *counts, 1)
            yield NiimbotPacket(0x85, header + line_data)

    async def get_info(self, key):
        response = await self.send_command(RequestCodeEnum.GET_INFO, bytes((key,)))

        match key:
            case InfoEnum.DEVICESERIAL:
                return response.data.hex()
            case InfoEnum.SOFTVERSION:
                return packet_to_int(response) / 100
            case InfoEnum.HARDVERSION:
                return packet_to_int(response) / 100
            case _:
                return packet_to_int(response)

        return None

    async def get_rfid(self):
        packet = await self.send_command(RequestCodeEnum.GET_RFID, b"\x01")
        data = packet.data

        if data[0] == 0:
            return None
        uuid = data[0:8].hex()
        idx = 8

        barcode_len = data[idx]
        idx += 1
        barcode = data[idx: idx + barcode_len].decode()

        idx += barcode_len
        serial_len = data[idx]
        idx += 1
        serial = data[idx: idx + serial_len].decode()

        idx += serial_len

        total_len, used_len, type_ = struct.unpack(">HHB", data[idx:])
        return {
            "uuid": uuid,
            "barcode": barcode,
            "serial": serial,
            "used_len": used_len,
            "total_len": total_len,
            "type": type_,
        }

    async def heartbeat(self):
        packet = await self.send_command(RequestCodeEnum.HEARTBEAT, b"\x01")
        closing_state = None
        power_level = None
        paper_state = None
        rfid_read_state = None

        match len(packet.data):
            case 20:
                paper_state = packet.data[18]
                rfid_read_state = packet.data[19]
            case 13:
                closing_state = packet.data[9]
                power_level = packet.data[10]
                paper_state = packet.data[11]
                rfid_read_state = packet.data[12]
            case 19:
                closing_state = packet.data[15]
                power_level = packet.data[16]
                paper_state = packet.data[17]
                rfid_read_state = packet.data[18]
            case 10:
                closing_state = packet.data[8]
                power_level = packet.data[9]
                rfid_read_state = packet.data[8]
            case 9:
                closing_state = packet.data[8]

        return {
            "closing_state": closing_state,
            "power_level": power_level,
            "paper_state": paper_state,
            "rfid_read_state": rfid_read_state,
        }

    async def set_label_type(self, n):
        assert 1 <= n <= 3
        packet = await self.send_command(RequestCodeEnum.SET_LABEL_TYPE, bytes((n,)))
        return bool(packet.data[0])

    async def set_label_density(self, n):
        assert 1 <= n <= 5  # B21 has 5 levels, not sure for D11
        packet = await self.send_command(RequestCodeEnum.SET_LABEL_DENSITY, bytes((n,)))
        return bool(packet.data[0])

    async def start_print(self):
        packet = await self.send_command(RequestCodeEnum.START_PRINT, b"\x01")
        return bool(packet.data[0])

    async def end_print(self):
        packet = await self.send_command(RequestCodeEnum.END_PRINT, b"\x01")
        return bool(packet.data[0])

    async def start_page_print(self):
        packet = await self.send_command(RequestCodeEnum.START_PAGE_PRINT, b"\x01")
        return bool(packet.data[0])

    async def end_page_print(self):
        packet = await self.send_command(RequestCodeEnum.END_PAGE_PRINT, b"\x01")
        return bool(packet.data[0])

    async def allow_print_clear(self):
        packet = await self.send_command(RequestCodeEnum.ALLOW_PRINT_CLEAR, b"\x01")
        return bool(packet.data[0])

    async def set_dimension(self, rows, columns):
        packet = await self.send_command(
            RequestCodeEnum.SET_DIMENSION, struct.pack(">HH", rows, columns)
        )
        return bool(packet.data[0])

    async def set_quantity(self, n):
        packet = await self.send_command(RequestCodeEnum.SET_QUANTITY, struct.pack(">H", n))
        return bool(packet.data[0])

    async def get_print_status(self):
        packet = await self.send_command(RequestCodeEnum.GET_PRINT_STATUS, b"\x01")

        page, progress1, progress2 = struct.unpack(">HBB", packet.data[:4])
        return {"page": page, "progress1": progress1, "progress2": progress2}
