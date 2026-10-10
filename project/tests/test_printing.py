"""Run: project/.venv/bin/python -m unittest discover -s project/tests -v"""
import asyncio
import io
import os
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / 'NiimPrintX' / 'NiimPrintX'))
from nimmy.bluetooth import BLETransport
from nimmy.printer import PrinterClient, RequestCodeEnum
from nimmy.packet import NiimbotPacket
from nimmy.exception import BLEException, PrinterException
# app uses relative paths for its existing upload folder.
previous_cwd = os.getcwd()
os.chdir(PROJECT)
import app as warehouse
os.chdir(previous_cwd)


def printer():
    return PrinterClient(SimpleNamespace(name='B31-test'))


def decode_rows(packets, size):
    raster = bytearray()
    for row, packet in enumerate(packets):
        y, a, b, c, repeat = struct.unpack('>H3BB', packet.data[:6])
        assert y == row and repeat == 1
        payload = packet.data[6:]
        assert a + b + c == sum(byte.bit_count() for byte in payload)
        raster.extend(payload)
    return ImageOps.invert(Image.frombytes('1', size, bytes(raster)).convert('L'))


class RasterTests(unittest.TestCase):
    def test_complete_25mm_frame_survives_wire_encoding(self):
        image = Image.new('1', (384, 240), 1)
        ImageDraw.Draw(image).rectangle((16, 20, 375, 219), outline=0, width=2)
        packets = list(printer()._encode_image(image))
        self.assertEqual(len(packets), 240)
        result = decode_rows(packets, image.size)
        self.assertIsNone(ImageChops.difference(image.convert('L'), result).getbbox())
        self.assertEqual(ImageOps.invert(result).getbbox(), (16, 20, 376, 220))

    def test_non_byte_width_is_padded_on_right(self):
        image = Image.new('1', (383, 2), 1)
        image.putpixel((0, 0), 0)
        image.putpixel((382, 1), 0)
        result = decode_rows(list(printer()._encode_image(image)), image.size)
        self.assertIsNone(ImageChops.difference(image.convert('L'), result).getbbox())

    def test_offsets_preserve_page_and_white_margins(self):
        image = Image.new('RGB', (24, 30), 'white')
        image.putpixel((10, 10), (0, 0, 0))
        for dx, dy in ((3, 4), (-3, -4)):
            with self.subTest(dx=dx, dy=dy):
                packets = list(printer()._encode_image(image, dy, dx))
                self.assertEqual(len(packets), 30)
                result = decode_rows(packets, image.size)
                self.assertEqual(ImageOps.invert(result).getbbox(), (10+dx, 10+dy, 11+dx, 11+dy))

    def test_real_label_generator_dimensions_and_border(self):
        original = ImageFont.truetype
        font = '/System/Library/Fonts/Supplemental/Arial.ttf'
        # Production is used on Windows; substitute only its platform-specific font path.
        if not Path(font).exists():
            font = 'DejaVuSans.ttf'
        def load_font(path, size, *args, **kwargs):
            return original(font if path == 'C:/Windows/Fonts/Arial.ttf' else path, size, *args, **kwargs)
        original_open = Image.open
        def open_image(path, *args, **kwargs):
            return original_open(PROJECT / path if path == 'warehouse.png' else path, *args, **kwargs)
        with patch.object(ImageFont, 'truetype', side_effect=load_font), patch.object(Image, 'open', side_effect=open_image):
            image = Image.open(warehouse.generate_qr_image_for_print('123', {'id': '123', 'product': 'Болт', 'available_count': 5}))
        self.assertEqual(image.size, (384, 240))
        self.assertEqual([y for y in range(240) if image.getpixel((16, y)) == 0], list(range(20, 220)))
        self.assertIsNone(ImageChops.difference(image.convert('L'), decode_rows(list(printer()._encode_image(image)), image.size)).getbbox())


class PrintJobTests(unittest.IsolatedAsyncioTestCase):
    def setup_job(self):
        p = printer()
        for name in ('set_label_density', 'set_label_type', 'start_print', 'start_page_print', 'set_dimension', 'set_quantity', 'end_page_print', 'end_print'):
            setattr(p, name, AsyncMock(return_value=True))
        p.get_print_status = AsyncMock(return_value={'page': 1})
        p.write_raw = AsyncMock()
        return p

    async def test_two_jobs_keep_dimensions_and_wait_for_finish_ack(self):
        p = self.setup_job()
        p.end_print.side_effect = [False, True, False, True]
        p.get_print_status.side_effect = [{'page': 0}, {'page': 1}, {'page': 0}, {'page': 1}]
        for _ in range(2):
            with patch('nimmy.printer.asyncio.sleep', new=AsyncMock()):
                await p.print_image(Image.new('1', (384, 240), 1), vertical_offset=5)
        self.assertEqual(p.end_print.await_count, 4)
        self.assertEqual(p.set_dimension.await_count, 2)
        p.set_dimension.assert_awaited_with(240, 384)
        rows = [struct.unpack('>H', call.args[0].data[:2])[0] for call in p.write_raw.await_args_list]
        self.assertEqual(rows, list(range(240)) * 2)

    async def test_rejected_setup_stops_before_page_data(self):
        p = self.setup_job()
        p.set_label_type.return_value = False
        with self.assertRaisesRegex(PrinterException, 'label type'):
            await p.print_image(Image.new('1', (8, 1), 1))
        p.start_print.assert_not_awaited()
        p.write_raw.assert_not_awaited()

    async def test_transport_error_is_not_swallowed(self):
        p = printer()
        p.transport.write = AsyncMock(side_effect=BLEException('disconnected'))
        with self.assertRaises(BLEException):
            await p.write_raw(NiimbotPacket(0x85, b'123'))

    async def test_finish_has_deadline(self):
        p = self.setup_job()
        p.get_print_status.return_value = {'page': 0}
        with self.assertRaisesRegex(PrinterException, 'completion'):
            await p.print_image(Image.new('1', (8, 1), 1), timeout=0.01)

    async def test_status_accepts_extended_payload(self):
        p = printer()
        p.send_command = AsyncMock(return_value=NiimbotPacket(0xB3, b'\x00\x01\x64\x64\x00\x00'))
        self.assertEqual(await p.get_print_status(), {'page': 1, 'progress1': 100, 'progress2': 100})

    async def test_only_matching_fragmented_response_acknowledges_command(self):
        p = printer()
        p.transport.client = SimpleNamespace(is_connected=True)
        async def write(*args):
            p.notification_handler(None, NiimbotPacket(0xD3, b'\x00\x78').to_bytes())
            self.assertFalse(p.notification_event.is_set())
            response = NiimbotPacket(0x14, b'\x01').to_bytes()
            p.notification_handler(None, response[:3])
            self.assertFalse(p.notification_event.is_set())
            p.notification_handler(None, response[3:] + NiimbotPacket(0xDD, b'\x00').to_bytes())
        p.transport.write = write
        self.assertTrue(await p.set_dimension(240, 384))

    async def test_command_timeout_is_reported(self):
        p = printer()
        p.transport.client = SimpleNamespace(is_connected=True)
        p.transport.write = AsyncMock()
        with self.assertRaisesRegex(PrinterException, 'SET_DIMENSION'):
            await p.send_command(RequestCodeEnum.SET_DIMENSION, b'1234', timeout=0.01)

    async def test_asynchronous_printer_error_stops_rows(self):
        p = printer()
        p.transport.write = AsyncMock()
        p.notification_event.set()  # Previous setup command was already acknowledged.
        p.notification_handler(None, NiimbotPacket(0xDB, b'\x04').to_bytes())
        with self.assertRaisesRegex(PrinterException, '04'):
            await p.write_raw(NiimbotPacket(0x85, b'123'))
        p.transport.write.assert_not_awaited()

    async def test_cli_disconnects_and_propagates_print_failure(self):
        from NiimPrintX.NiimPrintX.cli import command
        p = self.setup_job()
        p.connect = AsyncMock(return_value=True)
        p.disconnect = AsyncMock()
        p.print_image = AsyncMock(side_effect=BLEException('connection lost'))
        with patch.object(command, 'find_device', new=AsyncMock(return_value=p.device)), patch.object(command, 'PrinterClient', return_value=p):
            with self.assertRaisesRegex(BLEException, 'connection lost'):
                await command._print('b31', 3, Image.new('1', (384, 240), 1), 1, 0, 0)
        p.disconnect.assert_awaited_once()



class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_fragment_size_and_write_mode(self):
        for properties, expected_response in ((['write', 'write-without-response'], True), (['write-without-response'], False)):
            with self.subTest(properties=properties):
                transport = BLETransport()
                char = SimpleNamespace(properties=properties, max_write_without_response_size=20)
                transport.client = SimpleNamespace(is_connected=True, services=SimpleNamespace(get_characteristic=lambda _: char), write_gatt_char=AsyncMock())
                data = bytes(range(61))
                with patch('nimmy.bluetooth.asyncio.sleep', new=AsyncMock()):
                    await transport.write(data, 'uuid')
                calls = transport.client.write_gatt_char.await_args_list
                self.assertEqual(b''.join(call.args[1] for call in calls), data)
                self.assertTrue(all(call.kwargs['response'] == expected_response for call in calls))
                if not expected_response:
                    self.assertEqual([len(call.args[1]) for call in calls], [20, 20, 20, 1])


class RouteTests(unittest.TestCase):
    def test_failure_is_http_500_success_is_200_and_lock_released(self):
        from NiimPrintX.NiimPrintX.cli.command import niimbot_cli
        for failure, expected in ((RuntimeError('printer failed'), 500), (None, 200)):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as folder:
                with patch.dict(warehouse.app.config, UPLOAD_FOLDER=folder), patch.object(warehouse, 'load_items', return_value=[{'id': '123'}]), patch.object(warehouse, 'generate_qr_image_for_print', return_value=io.BytesIO(b'PNG')), patch.object(niimbot_cli, 'main', side_effect=failure) as run:
                    argv = list(sys.argv)
                    response = warehouse.app.test_client().get('/api/print_item/123')
                    self.assertEqual(response.status_code, expected)
                    self.assertEqual(sys.argv, argv)
                    self.assertFalse(warehouse.printer_lock.locked())
                    self.assertEqual(list(Path(folder).iterdir()), [])
                    self.assertFalse(run.call_args.kwargs['standalone_mode'])

    def test_busy_printer_rejects_overlapping_request(self):
        with patch.object(warehouse, 'load_items', return_value=[{'id': '123'}]):
            warehouse.printer_lock.acquire()
            try:
                self.assertEqual(warehouse.app.test_client().get('/api/print_item/123').status_code, 409)
            finally:
                warehouse.printer_lock.release()


if __name__ == '__main__':
    unittest.main()
