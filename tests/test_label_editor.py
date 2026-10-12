import io
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops

from warehouse import create_app, labels
from warehouse.routes import printing


class LabelEditorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = create_app({
            'TESTING': True,
            'UPLOAD_FOLDER': self.directory.name,
            'LABEL_TEMPLATES_FILE': str(Path(self.directory.name) / 'templates.json'),
        })
        context = self.app.app_context()
        context.push()
        self.addCleanup(context.pop)
        self.client = self.app.test_client()

    def template(self, **overrides):
        el = dict(type='field', x=24, y=76, width=200, height=70, field='product', prefix='Изделие: ', font_size=20)
        el.update(overrides)
        return dict(name='Мой шаблон', elements=[el])

    def test_new_label_preserves_calibrated_frame_and_header(self):
        background = Image.open(labels.label_background_image())
        self.assertEqual(background.size, (384, 240))
        self.assertEqual(background.getpixel((16, 20)), (0, 0, 0))
        self.assertEqual(background.getpixel((383, 219)), (0, 0, 0))
        for box in ((0, 0, 384, 20), (0, 220, 384, 240), (24, 76, 375, 211)):
            self.assertEqual(background.crop(box).getextrema(), ((255,255),) * 3)
        with patch.object(printing, 'load_items', return_value=[]):
            response = self.client.post('/api/label-templates/preview', json={'name':'Новый', 'elements':[]})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(ImageChops.difference(background, Image.open(io.BytesIO(response.data))).getbbox())

    def test_rejects_artwork_outside_locked_body_and_bad_payloads(self):
        for overrides in ({'x':0}, {'y':60}, {'width':1000}, {'height':200}, {'x':True}, {'type':'qr','width':100,'height':80}):
            response = self.client.post('/api/label-templates', json=self.template(**overrides))
            self.assertEqual(response.status_code, 400, overrides)
        for value in ([], {}, None, {'name':'x','elements':[None]}):
            self.assertEqual(self.client.post('/api/label-templates', json=value).status_code, 400)

    def test_save_reload_print_uses_same_renderer_and_real_data(self):
        template = self.template()
        response = self.client.post('/api/label-templates', json=template)
        self.assertEqual(response.status_code, 200)
        key = response.json['id']
        store = self.client.get('/api/label-templates').json
        self.assertEqual(store['active'], key)
        self.assertEqual(store['templates'][key]['name'], template['name'])
        # Preview uses the same sample as the actual print call.
        item = {'id':'DEMO-001','product':'Пример изделия','ШИБФ':'123.456','available_count':10}
        response = self.client.post('/api/label-templates/preview', json=template)
        printed = labels.generate_qr_image_for_print(item['id'], item)
        self.assertEqual(response.data, printed.getvalue())
        other = labels.generate_qr_image_for_print('other', dict(item, product='Другое изделие'))
        self.assertNotEqual(printed.getvalue(), other.getvalue())
        background = Image.open(labels.label_background_image())
        actual = Image.open(printed)
        self.assertIsNone(ImageChops.difference(background.crop((0,0,384,76)), actual.crop((0,0,384,76))).getbbox())
        self.assertEqual(self.client.post('/api/label-templates/active', json={'id':None}).status_code, 200)
        self.assertIsNone(self.client.get('/api/label-templates').json['active'])

    def test_custom_artwork_reaches_printer_without_changing_settings(self):
        from warehouse.vendor.niimprintx.cli.command import niimbot_cli
        self.client.post('/api/label-templates', json=self.template())
        item = {'id':'123','product':'Деталь'}
        expected = labels.generate_qr_image_for_print('123', item).getvalue()
        captured = []
        def fake_print(*, args, **kwargs):
            self.assertEqual(args[:7], ['print','-m','b31','-d','3','-n','1'])
            captured.append(Path(args[args.index('-i') + 1]).read_bytes())
        with patch.dict(self.app.config, UPLOAD_FOLDER=self.directory.name), patch.object(printing, 'load_items', return_value=[item]), patch.object(niimbot_cli, 'main', side_effect=fake_print):
            self.assertEqual(self.client.get('/api/print_item/123').status_code, 200)
        self.assertEqual(captured, [expected])
        self.assertFalse(self.app.extensions['printer_lock'].locked())

    def test_image_render_and_client_geometry_cannot_change_page(self):
        image = io.BytesIO()
        Image.new('RGB', (20,20), 'black').save(image, format='PNG')
        template = self.template(type='image', width=40, height=40, src=base64.b64encode(image.getvalue()).decode())
        template.update(width=900, height=900, margin=0)
        response = self.client.post('/api/label-templates/preview', json=template)
        self.assertEqual(response.status_code, 200)
        result = Image.open(io.BytesIO(response.data))
        self.assertEqual(result.size, (384,240))
        self.assertEqual(result.getpixel((30,80)), (0,0,0))
        self.assertEqual(result.getpixel((23,80)), (255,255,255))

    def test_image_and_qr_validation_and_text_overflow(self):
        response = self.client.post('/api/label-templates/preview', json=self.template(type='text', text='Очень длинный текст ' * 20, width=10, height=10))
        self.assertEqual(response.status_code, 400)
        response = self.client.post('/api/label-templates', json=self.template(type='image', src='bad'))
        self.assertEqual(response.status_code, 400)
        response = self.client.post('/api/label-templates/preview', json=self.template(type='qr', width=130, height=130))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Image.open(io.BytesIO(response.data)).size, (384,240))


if __name__ == '__main__':
    unittest.main()
