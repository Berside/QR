"""Fixed B31 layout, user artwork validation, rendering and template storage."""
import base64
import binascii
import io
import json
import os
from pathlib import Path
from threading import Lock

import qrcode
from PIL import Image, ImageDraw, ImageFont, ImageOps

# Matches the existing 203 DPI, 48 × 30 mm label and its calibrated artwork.
WIDTH, HEIGHT = 384, 240
BODY = {'x': 24, 'y': 76, 'width': 351, 'height': 135}
STORE_LOCK = Lock()


def font(size):
    for name in ('C:/Windows/Fonts/Arial.ttf', '/System/Library/Fonts/Supplemental/Arial.ttf',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    raise ValueError('Не найден шрифт Arial или DejaVu Sans с поддержкой кириллицы')


def decode_image(value):
    if not isinstance(value, str) or len(value) > 2_000_000:
        raise ValueError('Изображение должно быть PNG или JPEG размером до 1 МБ')
    try:
        raw = base64.b64decode(value.split(',', 1)[-1], validate=True)
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in ('PNG', 'JPEG') or source.width * source.height > 4_000_000:
                raise ValueError('Допустимы PNG/JPEG до 4 мегапикселей')
            source.load()
            return source.convert('RGBA')
    except (OSError, binascii.Error, Image.DecompressionBombError) as exc:
        raise ValueError('Не удалось прочитать изображение') from exc


def validate_template(value):
    if not isinstance(value, dict):
        raise ValueError('Неверный шаблон')
    name = value.get('name', '')
    elements = value.get('elements')
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        raise ValueError('Введите название шаблона (до 80 символов)')
    if not isinstance(elements, list) or len(elements) > 40:
        raise ValueError('Допустимо не более 40 элементов')
    result = {'name': name.strip(), 'elements': []}
    for element in elements:
        if not isinstance(element, dict) or element.get('type') not in ('text', 'field', 'qr', 'image', 'line'):
            raise ValueError('Неизвестный элемент')
        clean = {'type': element['type']}
        for key in ('x', 'y', 'width', 'height'):
            number = element.get(key)
            if type(number) is not int:
                raise ValueError('Координаты и размеры должны быть целыми числами')
            clean[key] = number
        x, y, w, h = (clean[k] for k in ('x', 'y', 'width', 'height'))
        if x < BODY['x'] or y < BODY['y'] or w < 1 or h < 1 or x + w > 375 or y + h > 211:
            raise ValueError('Элемент выходит за фиксированную рабочую область')
        if clean['type'] == 'qr' and (w != h or w < 58):
            raise ValueError('QR-код должен быть квадратным, от 58 точек')
        for key in ('text', 'field', 'prefix'):
            content = element.get(key, '')
            if not isinstance(content, str) or len(content) > 1000:
                raise ValueError('Текст слишком длинный (максимум 1000 символов)')
            clean[key] = content
        size = element.get('font_size', 20)
        if type(size) is not int or not 10 <= size <= 48:
            raise ValueError('Размер шрифта: от 10 до 48 точек')
        clean['font_size'] = size
        clean['align'] = element.get('align', 'left')
        if clean['align'] not in ('left', 'center', 'right'):
            raise ValueError('Неверное выравнивание')
        if clean['type'] == 'image':
            decode_image(element.get('src'))
            clean['src'] = element['src']
        result['elements'].append(clean)
    return result


def render(template, item, background):
    final = Image.open(background).convert('RGB')
    for el in template['elements']:
        w, h = el['width'], el['height']
        layer = Image.new('RGB', (w, h), 'white')
        draw = ImageDraw.Draw(layer)
        kind = el['type']
        if kind in ('text', 'field'):
            text = el['text'] if kind == 'text' else el['prefix'] + str(item.get(el['field'], ''))
            for size in range(el['font_size'], 9, -1):
                face = font(size)
                lines = []
                for paragraph in text.split('\n'):
                    line = ''
                    for char in paragraph:
                        if line and draw.textlength(line + char, font=face) > w:
                            lines.append(line)
                            line = ''
                        line += char
                    lines.append(line)
                spacing = size + 3
                if len(lines) * spacing <= h:
                    break
            if len(lines) * spacing > h or any(draw.textlength(line, font=face) > w for line in lines):
                raise ValueError('Текст не помещается: увеличьте блок или сократите содержимое')
            for i, line in enumerate(lines):
                length = draw.textlength(line, font=face)
                x = 0 if el['align'] == 'left' else (w - length) / (2 if el['align'] == 'center' else 1)
                draw.text((x, i * spacing), line, font=face, fill='black', anchor='lt')
        elif kind == 'qr':
            qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=1, border=4)
            qr.add_data(str(item.get('id', 'DEMO-001')))
            qr.make(fit=True)
            code = qr.make_image().convert('RGB')
            scale = w // code.width
            if scale < 2:
                raise ValueError('QR-код слишком мал для этих данных: увеличьте блок')
            code = code.resize((code.width * scale, code.height * scale), Image.Resampling.NEAREST)
            layer.paste(code, ((w - code.width) // 2, (h - code.height) // 2))
        elif kind == 'image':
            source = ImageOps.contain(decode_image(el['src']), (w, h), Image.Resampling.LANCZOS)
            layer.paste(source, ((w - source.width) // 2, (h - source.height) // 2), source)
        else:
            draw.rectangle((0, 0, w - 1, h - 1), fill='black')
        final.paste(layer, (el['x'], el['y']))
    output = io.BytesIO()
    final.save(output, format='PNG')
    output.seek(0)
    return output


def read_store(app):
    path = Path(app.config['LABEL_TEMPLATES_FILE'])
    if not path.exists():
        return {'active': None, 'templates': {}}
    return json.loads(path.read_text(encoding='utf-8'))


def write_store(app, store):
    path = Path(app.config['LABEL_TEMPLATES_FILE'])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(store, ensure_ascii=False), encoding='utf-8')
    os.replace(temporary, path)


def active_template(app):
    store = read_store(app)
    value = store['templates'].get(store['active'])
    return validate_template(value) if value else None
