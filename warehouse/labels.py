"""Calibrated B31 label artwork (203 DPI, 48 x 30 mm).

Keep the artwork geometry independent of the printer's 600-dot printhead.
The 6 mm media gap is handled by the printer's label sensor.
"""
from io import BytesIO
from pathlib import Path
import qrcode
from flask import current_app as app
from PIL import Image, ImageDraw
from .label_editor import active_template, font as label_font, render as render_label

# Excel field names and their order on the default label.
LABEL_COLUMNS = ['product', 'ШИБФ', 'available_count']


def generate_qr_image(data):
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=4, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    return qr


def generate_qr_image_for_print(data, item, columns=None):
    template = active_template(app)
    if template is not None:
        return render_label(template, dict(item, id=data), label_background_image())
    return generate_default_label(data, item, columns)


def label_background_image():
    return generate_default_label('', {}, header_only=True)


def generate_default_label(data, item, columns=None, header_only=False):
    DPI = 203

    def mm_to_px(mm):
        return round(mm / 25.4 * DPI)
    LABEL_WIDTH_MM = 48
    LABEL_HEIGHT_MM = 30
    ARTWORK_HEIGHT_MM = 25
    SHIFT_X_MM = 1
    TEXT_FONT_SIZE = 30
    MIN_TEXT_FONT_SIZE = 10
    HEADER_FONT_SIZE = 20
    HEADER_HEIGHT_MM = 6
    QR_SIZE_MM = 17
    MARGIN_MM = 1
    TEXT_QR_GAP_MM = 1
    FIELD_GAP_MM = 1
    LINE_SPACING_MM = 0.5
    HEADER_IMAGE_PATH = str(Path(__file__).parent / 'assets' / 'warehouse.png')
    HEADER_TITLE = 'АО "ГПТП "ГРАНИТ"'
    target_width = mm_to_px(LABEL_WIDTH_MM)
    target_height = mm_to_px(LABEL_HEIGHT_MM)
    artwork_height = mm_to_px(ARTWORK_HEIGHT_MM)
    artwork_top = (target_height - artwork_height) // 2
    shift_x = mm_to_px(SHIFT_X_MM)
    margin = mm_to_px(MARGIN_MM)
    header_height = mm_to_px(HEADER_HEIGHT_MM)
    qr_side = mm_to_px(QR_SIZE_MM)
    text_qr_gap = mm_to_px(TEXT_QR_GAP_MM)
    field_gap = mm_to_px(FIELD_GAP_MM)
    line_spacing = mm_to_px(LINE_SPACING_MM)
    final = Image.new('RGB', (target_width, target_height), 'white')
    draw = ImageDraw.Draw(final)
    frame_left = margin + shift_x
    frame_top = artwork_top
    frame_right = target_width - margin - 1 + shift_x
    frame_bottom = artwork_top + artwork_height - 1
    frame_right = min(frame_right, target_width - 1)
    draw.rectangle((frame_left, frame_top, frame_right, frame_bottom), outline='black', width=2)
    header_top = frame_top + margin
    separator_y = frame_top + header_height
    header_image_x = frame_left + margin
    header_image_y = header_top
    header_image_max_height = header_height - margin * 2
    header_text_x = frame_left + margin
    if HEADER_IMAGE_PATH:
        try:
            header_img = Image.open(HEADER_IMAGE_PATH).convert('RGBA')
            original_width, original_height = header_img.size
            scale = min(header_image_max_height / original_height, 1.0)
            new_width = max(1, round(original_width * scale))
            new_height = max(1, round(original_height * scale))
            header_img = header_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            header_image_y = header_top + (header_height - new_height) // 2
            final.paste(header_img, (header_image_x, header_image_y), header_img)
            header_text_x = header_image_x + new_width + field_gap
        except Exception as e:
            print(f'Не удалось загрузить PNG шапки: {e}')
    header_font = label_font(HEADER_FONT_SIZE)
    header_bbox = draw.textbbox((0, 0), HEADER_TITLE, font=header_font)
    header_text_height = header_bbox[3] - header_bbox[1]
    header_text_y = header_top + (header_height - header_text_height) // 2 - header_bbox[1]
    draw.text((header_text_x, header_text_y), HEADER_TITLE, fill='black', font=header_font)
    draw.line((frame_left, separator_y, frame_right, separator_y), fill='black', width=2)
    body_left = frame_left + margin
    body_right = frame_right - margin
    body_top = separator_y + margin
    body_bottom = frame_bottom - margin
    body_width = body_right - body_left
    body_height = body_bottom - body_top
    if header_only:
        buf = BytesIO()
        final.save(buf, format='PNG')
        buf.seek(0)
        return buf
    qr = generate_qr_image(data)
    qr_img = qr.make_image(fill_color='black', back_color='white').convert('RGB')
    qr_img = qr_img.resize((qr_side, qr_side), Image.Resampling.NEAREST)
    qr_x = body_right - qr_side
    qr_y = body_top + (body_height - qr_side) // 2
    qr_x = max(body_left, qr_x)
    qr_y = max(body_top, qr_y)
    final.paste(qr_img, (qr_x, qr_y))
    text_left = body_left
    text_right = qr_x - text_qr_gap
    text_width = text_right - text_left
    text_top = body_top
    text_bottom = body_bottom
    text_height = text_bottom - text_top
    available_columns = columns if columns is not None else item.keys()
    label_columns = [column for column in LABEL_COLUMNS if column in available_columns]

    def wrap_text_by_pixels(value, font, max_width):
        words = value.split()
        if not words:
            return ['']
        lines = []
        current = ''
        for word in words:
            test = word if not current else current + ' ' + word
            bbox = draw.textbbox((0, 0), test, font=font)
            width = bbox[2] - bbox[0]
            if width <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = ''
                part = ''
                for char in word:
                    test_part = part + char
                    bbox = draw.textbbox((0, 0), test_part, font=font)
                    part_width = bbox[2] - bbox[0]
                    if part_width <= max_width:
                        part = test_part
                    else:
                        if part:
                            lines.append(part)
                        part = char
                current = part
        if current:
            lines.append(current)
        return lines or ['']

    def build_lines(font):
        lines = []
        for column in label_columns:
            value = str(item.get(column, '')).strip()
            if not value:
                continue
            label = f'{column}:'
            label_bbox = draw.textbbox((0, 0), label, font=font)
            label_width = label_bbox[2] - label_bbox[0]
            value_width = max(1, text_width - label_width - field_gap)
            value_lines = wrap_text_by_pixels(value, font, value_width)
            lines.append((label, value_lines[0]))
            lines.extend((('', line) for line in value_lines[1:]))
        return lines
    selected_font = None
    selected_lines = None
    for font_size in range(TEXT_FONT_SIZE, MIN_TEXT_FONT_SIZE - 1, -1):
        test_font = label_font(font_size)
        test_lines = build_lines(test_font)
        total_height = 0
        for label, value in test_lines:
            bbox = draw.textbbox((0, 0), 'Ag', font=test_font)
            line_height = bbox[3] - bbox[1]
            total_height += line_height + line_spacing
        total_height -= line_spacing
        if total_height <= text_height:
            selected_font = test_font
            selected_lines = test_lines
            break
    if selected_font is None:
        selected_font = label_font(MIN_TEXT_FONT_SIZE)
        selected_lines = build_lines(selected_font)
    current_y = text_top
    for label, value in selected_lines:
        bbox = draw.textbbox((0, 0), 'Ag', font=selected_font)
        line_height = bbox[3] - bbox[1]
        if label == '':
            draw.text((text_left, current_y), value, fill='black', font=selected_font)
        else:
            draw.text((text_left, current_y), label, fill='black', font=selected_font)
            label_bbox = draw.textbbox((0, 0), label, font=selected_font)
            label_width = label_bbox[2] - label_bbox[0]
            value_x = text_left + label_width + field_gap
            draw.text((value_x, current_y), value, fill='black', font=selected_font)
        current_y += line_height + line_spacing
    final = final.convert('1')
    buf = BytesIO()
    final.save(buf, format='PNG')
    buf.seek(0)
    return buf


def generate_qr_image_for_page(data):
    qr = generate_qr_image(data)
    img = qr.make_image(fill_color='black', back_color='white')
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf
