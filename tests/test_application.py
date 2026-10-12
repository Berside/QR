"""Exercise the public workflow against temporary workbooks and storage."""
import io
import os
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from warehouse import create_app


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.app = create_app({
            'TESTING': True,
            'UPLOAD_FOLDER': str(self.root / 'uploads'),
            'LABEL_TEMPLATES_FILE': str(self.root / 'templates.json'),
        })
        self.client = self.app.test_client()

    def upload_workbook(self):
        workbook = io.BytesIO()
        pd.DataFrame([{
            'id': '001', 'product': 'Болт', 'ШИБФ': 'АБ.123',
            'available_count': 5, 'image': '', 'extra': 'Сохранить',
        }]).to_excel(workbook, index=False)
        workbook.seek(0)
        response = self.client.post('/api/select_excel', data={
            'excel_file': (workbook, 'warehouse.xlsx'),
        })
        self.assertEqual(response.status_code, 200)

    def test_workbook_upload_edit_add_delete_and_download(self):
        self.upload_workbook()
        self.assertEqual(self.client.get('/api/get_item/001').json['extra'], 'Сохранить')
        response = self.client.put('/api/edit_item/001', json={
            'values': {'product': 'Гайка', 'id': 'changed'},
        })
        self.assertEqual(response.status_code, 200)
        item = self.client.get('/api/get_item/001').json
        self.assertEqual(item['product'], 'Гайка')
        self.assertEqual(item['extra'], 'Сохранить')

        response = self.client.post('/api/add_item', data={
            'product': 'Шайба', 'extra': 'Новый столбец',
            'image': (io.BytesIO(b'image data'), 'part.png'),
        })
        self.assertEqual(response.status_code, 200)
        new_id = response.json['id']
        item = self.client.get('/api/get_item/' + new_id).json
        self.assertEqual(item['extra'], 'Новый столбец')
        with self.client.get(item['image']) as image:
            self.assertEqual(image.data, b'image data')

        with self.client.get('/api/download_excel') as response:
            self.assertEqual(response.status_code, 200)
            downloaded = pd.read_excel(io.BytesIO(response.data), dtype={'id': str})
        self.assertEqual(list(downloaded.columns), ['id', 'product', 'ШИБФ', 'available_count', 'image', 'extra'])
        self.assertEqual(downloaded['id'].tolist(), ['001', new_id])
        for item_id in ('001', new_id):
            self.assertEqual(self.client.delete('/api/delete_item/' + item_id).status_code, 200)
        empty = pd.read_excel(self.app.config['EXCEL_FILE'])
        self.assertEqual(list(empty.columns), list(downloaded.columns))
        self.assertTrue(empty.empty)

    def test_pages_static_and_labels_after_upload(self):
        self.upload_workbook()
        for url in ('/', '/scan', '/print_labels', '/packing/print', '/label-editor',
                    '/static/style.css', '/static/jsQR.js', '/api/label-templates/background'):
            with self.subTest(url=url), self.client.get(url) as response:
                self.assertEqual(response.status_code, 200)
        self.assertIn('data:image/png;base64,', self.client.get('/print_labels').text)

    def test_packing_and_independent_app_instances(self):
        response = self.client.post('/api/add_to_list', json={'id': '001', 'product': 'Болт'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Болт', self.client.get('/packing/print').text)
        other = create_app({'TESTING': True, 'UPLOAD_FOLDER': str(self.root / 'other')})
        self.assertEqual(other.extensions['packing_list'], [])
        self.assertIsNone(other.config['EXCEL_FILE'])
        self.assertIsNot(other.extensions['printer_lock'], self.app.extensions['printer_lock'])
        self.assertEqual(self.client.post('/api/packing/reset').status_code, 200)
        self.assertEqual(self.app.extensions['packing_list'], [])

    def test_missing_and_invalid_workbook_requests(self):
        self.assertEqual(self.client.post('/api/select_excel').status_code, 400)
        self.assertEqual(self.client.post('/api/select_excel', data={
            'excel_file': (io.BytesIO(b'bad'), 'bad.txt'),
        }).status_code, 400)
        self.assertEqual(self.client.post('/api/add_item', data={'product': 'Болт'}).status_code, 400)
        self.assertEqual(self.client.get('/api/download_excel').status_code, 404)
        self.assertEqual(self.client.get('/api/get_item/missing').status_code, 404)
        self.assertEqual(self.client.get('/api/print_item/missing').status_code, 404)

    def test_starting_from_another_directory_preserves_paths(self):
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            other = create_app({'TESTING': True})
            self.assertEqual(Path(other.config['UPLOAD_FOLDER']), Path(other.instance_path) / 'uploads')
            with other.test_client().get('/static/style.css') as response:
                self.assertEqual(response.status_code, 200)
            with other.test_client().get('/api/label-templates/background') as response:
                self.assertEqual(response.status_code, 200)
        finally:
            os.chdir(previous)
