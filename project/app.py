import os
import uuid
from threading import Lock
from flask import Flask, render_template, request, jsonify, redirect, send_file, send_from_directory
import pandas as pd
import io
import json
from textwrap import wrap
import subprocess
import traceback
# import barcode
# from barcode.writer import ImageWriter
import qrcode
import base64 
from PIL import Image, ImageDraw, ImageFont
import tempfile
# import niimprint 
import sys
from io import BytesIO
from werkzeug.utils import secure_filename

from pathlib import Path


app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['EXCEL_FILE'] = None
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

EXCEL_COLUMNS = [
    'id', 'product', 'placement_location', 'current_count',
    'available_count', 'image', 'document', 'analogue',
]

packing_list = []
printer_lock = Lock()

# EXCEL_FILE = 'warehouse.xlsx'

# --- Функции для работы с Excel (как с базой данных) ---
def load_items():
    """Загружает данные из Excel."""
    excel_path = app.config.get('EXCEL_FILE')
    
    if not excel_path or not os.path.exists(excel_path):
        return []
    df = pd.read_excel(excel_path, dtype={'id': str}, keep_default_na=False)
    if 'id' not in df.columns:
        return []
    df['id'] = df['id'].str.strip()
    return df.to_dict(orient='records')

def save_items(items):
    """Сохраняет данные в Excel."""
    excel_path = app.config.get('EXCEL_FILE')
    if not excel_path:
        raise RuntimeError('Excel файл не выбран')
    # Keep the headers even when the last table row is deleted, while retaining
    # any extra columns present in a non-empty imported workbook.
    df = pd.DataFrame(items) if items else pd.DataFrame(columns=EXCEL_COLUMNS)
    df.to_excel(excel_path, index=False)


def generate_qr_image(data):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=4,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    # img = qr.make_image(fill_color="black", back_color="white")
    return qr

def generate_qr_image_for_print(data, item):

    # =========================================================
    # НАСТРОЙКИ
    # =========================================================

    DPI = 203

    def mm_to_px(mm):
        return round(mm / 25.4 * DPI)

    # ---------------------------------------------------------
    # Размер наклейки
    # ---------------------------------------------------------

    # Artwork width; independent of the B31 printhead width (600 dots).
    LABEL_WIDTH_MM = 48
    # Physical label only: the 6 mm gap is found by the gap sensor (label type 1).
    LABEL_HEIGHT_MM = 30
    ARTWORK_HEIGHT_MM = 25

    # ---------------------------------------------------------
    # Сдвиг всей печати вправо
    # ---------------------------------------------------------

    SHIFT_X_MM = 1

    # ---------------------------------------------------------
    # Максимальный размер основного текста
    #
    # Если текст не помещается, функция автоматически
    # уменьшит его.
    # ---------------------------------------------------------

    TEXT_FONT_SIZE = 30

    # Минимальный размер текста.
    # Ниже этого размера автоматически не опускаемся.
    MIN_TEXT_FONT_SIZE = 10

    # ---------------------------------------------------------
    # Размер текста шапки
    # ---------------------------------------------------------

    HEADER_FONT_SIZE = 20

    # ---------------------------------------------------------
    # Высота шапки
    # ---------------------------------------------------------

    HEADER_HEIGHT_MM = 6

    # ---------------------------------------------------------
    # Размер QR-кода
    #
    # ИМЕННО ОТ ЭТОГО РАЗМЕРА АВТОМАТИЧЕСКИ
    # РАССЧИТЫВАЕТСЯ ОБЛАСТЬ ТЕКСТА.
    # ---------------------------------------------------------

    QR_SIZE_MM = 17

    # ---------------------------------------------------------
    # Отступы
    # ---------------------------------------------------------

    MARGIN_MM = 1

    # Расстояние между текстом и QR
    TEXT_QR_GAP_MM = 1

    # Расстояние между названием поля и значением
    FIELD_GAP_MM = 1

    # Расстояние между строками
    LINE_SPACING_MM = 0.5

    # ---------------------------------------------------------
    # PNG КАРТИНКА В ШАПКЕ
    # ---------------------------------------------------------

    HEADER_IMAGE_PATH = "warehouse.png"

    # ---------------------------------------------------------
    # Текст шапки
    # ---------------------------------------------------------



    HEADER_TITLE = 'АО "ГПТП "ГРАНИТ"'

    # =========================================================
    # ПЕРЕВОДИМ РАЗМЕРЫ В PIXEL
    # =========================================================

    target_width = mm_to_px(LABEL_WIDTH_MM)

    target_height = mm_to_px(LABEL_HEIGHT_MM)
    artwork_height = mm_to_px(ARTWORK_HEIGHT_MM)
    artwork_top = (target_height - artwork_height) // 2

    shift_x = mm_to_px(
        SHIFT_X_MM
    )

    margin = mm_to_px(
        MARGIN_MM
    )

    header_height = mm_to_px(
        HEADER_HEIGHT_MM
    )

    qr_side = mm_to_px(
        QR_SIZE_MM
    )

    text_qr_gap = mm_to_px(
        TEXT_QR_GAP_MM
    )

    field_gap = mm_to_px(
        FIELD_GAP_MM
    )

    line_spacing = mm_to_px(
        LINE_SPACING_MM
    )

    # =========================================================
    # СОЗДАЁМ НАКЛЕЙКУ
    # =========================================================

    final = Image.new(
        "RGB",
        (target_width, target_height),
        "white"
    )

    draw = ImageDraw.Draw(final)

    # =========================================================
    # РАМКА
    # =========================================================

    frame_left = margin + shift_x

    frame_top = artwork_top

    frame_right = (
        target_width
        - margin
        - 1
        + shift_x
    )

    frame_bottom = artwork_top + artwork_height - 1

    # Не даём рамке выйти за изображение
    frame_right = min(
        frame_right,
        target_width - 1
    )

    draw.rectangle(
        (
            frame_left,
            frame_top,
            frame_right,
            frame_bottom
        ),
        outline="black",
        width=2
    )

    # =========================================================
    # ШАПКА
    # =========================================================

    header_top = (
        frame_top
        + margin
    )

    separator_y = (
        frame_top
        + header_height
    )

    # ---------------------------------------------------------
    # PNG КАРТИНКА ШАПКИ
    # ---------------------------------------------------------

    header_image_x = (
        frame_left
        + margin
    )

    header_image_y = header_top

    header_image_max_height = (
        header_height
        - margin * 2
    )

    header_text_x = (
        frame_left
        + margin
    )

    # ---------------------------------------------------------
    # Загружаем PNG
    # ---------------------------------------------------------

    if HEADER_IMAGE_PATH:

        try:

            header_img = Image.open(
                HEADER_IMAGE_PATH
            ).convert("RGBA")

            original_width, original_height = (
                header_img.size
            )

            # Масштабируем PNG так, чтобы он целиком
            # помещался по высоте шапки.

            scale = min(
                header_image_max_height / original_height,
                1.0
            )

            new_width = max(
                1,
                round(
                    original_width * scale
                )
            )

            new_height = max(
                1,
                round(
                    original_height * scale
                )
            )

            header_img = header_img.resize(
                (
                    new_width,
                    new_height
                ),
                Image.Resampling.LANCZOS
            )

            # Центрируем PNG по вертикали шапки

            header_image_y = (
                header_top
                + (
                    header_height
                    - new_height
                ) // 2
            )

            final.paste(
                header_img,
                (
                    header_image_x,
                    header_image_y
                ),
                header_img
            )

            # После картинки текст "Склад"
            # начинается справа от неё.

            header_text_x = (
                header_image_x
                + new_width
                + field_gap
            )

        except Exception as e:

            print(
                f"Не удалось загрузить PNG шапки: {e}"
            )

    # =========================================================
    # ТЕКСТ ШАПКИ
    # =========================================================

    header_font = ImageFont.truetype(
        "C:/Windows/Fonts/Arial.ttf",
        HEADER_FONT_SIZE
    )

    header_bbox = draw.textbbox(
        (0, 0),
        HEADER_TITLE,
        font=header_font
    )

    header_text_height = (
        header_bbox[3]
        - header_bbox[1]
    )

    header_text_y = (
        header_top
        + (
            header_height
            - header_text_height
        ) // 2
        - header_bbox[1]
    )

    draw.text(
        (
            header_text_x,
            header_text_y
        ),
        HEADER_TITLE,
        fill="black",
        font=header_font
    )

    # =========================================================
    # ГОРИЗОНТАЛЬНАЯ ЛИНИЯ
    # =========================================================

    draw.line(
        (
            frame_left,
            separator_y,
            frame_right,
            separator_y
        ),
        fill="black",
        width=2
    )

    # =========================================================
    # ТЕЛО НАКЛЕЙКИ
    # =========================================================

    body_left = (
        frame_left
        + margin
    )

    body_right = (
        frame_right
        - margin
    )

    body_top = (
        separator_y
        + margin
    )

    body_bottom = (
        frame_bottom
        - margin
    )

    body_width = (
        body_right
        - body_left
    )

    body_height = (
        body_bottom
        - body_top
    )

    # =========================================================
    # QR-КОД
    # =========================================================

    qr = generate_qr_image(data)

    qr_img = qr.make_image(
        fill_color="black",
        back_color="white"
    ).convert("RGB")

    # ЯВНО масштабируем QR
    qr_img = qr_img.resize(
        (
            qr_side,
            qr_side
        ),
        Image.Resampling.NEAREST
    )

    # ---------------------------------------------------------
    # QR всегда располагается справа.
    # ---------------------------------------------------------

    qr_x = (
        body_right
        - qr_side
    )

    # Центрируем QR вертикально в теле
    qr_y = (
        body_top
        + (
            body_height
            - qr_side
        ) // 2
    )

    # Защита
    qr_x = max(
        body_left,
        qr_x
    )

    qr_y = max(
        body_top,
        qr_y
    )

    final.paste(
        qr_img,
        (
            qr_x,
            qr_y
        )
    )

    # =========================================================
    # ОБЛАСТЬ ТЕКСТА
    # =========================================================

    # КЛЮЧЕВОЙ МОМЕНТ:
    #
    # Текстовая область заканчивается ровно перед QR.
    #
    # Поэтому какой бы QR_SIZE_MM ни был —
    # текст НИКОГДА не попадёт под QR.
    # =========================================================

    text_left = body_left

    text_right = (
        qr_x
        - text_qr_gap
    )

    text_width = (
        text_right
        - text_left
    )

    text_top = body_top

    text_bottom = body_bottom

    text_height = (
        text_bottom
        - text_top
    )

    # =========================================================
    # ДАННЫЕ
    # =========================================================

    product = str(
        item.get(
            "product",
            ""
        )
    )

    item_id = str(
        item.get(
            "id",
            ""
        )
    )

    available_count = str(
        item.get(
            "available_count",
            "0"
        )
    )

    # =========================================================
    # ФУНКЦИЯ ПЕРЕНОСА ПО PIXELS
    # =========================================================

    def wrap_text_by_pixels(
        value,
        font,
        max_width
    ):

        words = value.split()

        if not words:
            return [""]

        lines = []

        current = ""

        for word in words:

            test = (
                word
                if not current
                else current + " " + word
            )

            bbox = draw.textbbox(
                (0, 0),
                test,
                font=font
            )

            width = (
                bbox[2]
                - bbox[0]
            )

            if width <= max_width:

                current = test

            else:

                if current:
                    lines.append(
                        current
                    )

                # Если одно слово само длиннее
                # области — режем его.

                current = ""

                part = ""

                for char in word:

                    test_part = (
                        part + char
                    )

                    bbox = draw.textbbox(
                        (0, 0),
                        test_part,
                        font=font
                    )

                    part_width = (
                        bbox[2]
                        - bbox[0]
                    )

                    if part_width <= max_width:

                        part = test_part

                    else:

                        if part:
                            lines.append(
                                part
                            )

                        part = char

                current = part

        if current:
            lines.append(
                current
            )

        return lines or [""]

    # =========================================================
    # СОЗДАЁМ ТЕКСТОВЫЕ ДАННЫЕ
    # =========================================================

    # Здесь не фиксируем размер строк.
    #
    # Сначала пробуем TEXT_FONT_SIZE.
    # Если весь текст не помещается —
    # уменьшаем шрифт.
    # =========================================================

    def build_lines(font):

        lines = []

        # -----------------------------------------------------
        # Название
        # -----------------------------------------------------

        name_label = "Название:"

        name_lines = wrap_text_by_pixels(
            product,
            font,
            text_width
        )

        # Первая строка:
        #
        # Название: XXXXX
        #

        label_bbox = draw.textbbox(
            (0, 0),
            name_label,
            font=font
        )

        label_width = (
            label_bbox[2]
            - label_bbox[0]
        )

        value_width = (
            text_width
            - label_width
            - field_gap
        )

        name_lines = wrap_text_by_pixels(
            product,
            font,
            max(
                1,
                value_width
            )
        )

        lines.append(
            (
                name_label,
                name_lines[0]
            )
        )

        # Продолжение названия
        for line in name_lines[1:]:

            lines.append(
                (
                    "",
                    line
                )
            )

        # -----------------------------------------------------
        # ШИБ
        # -----------------------------------------------------

        lines.append(
            (
                "Шиб:",
                item_id
            )
        )

        # -----------------------------------------------------
        # Количество
        # -----------------------------------------------------

        lines.append(
            (
                "Количество:",
                available_count
            )
        )

        return lines

    # =========================================================
    # ПРОВЕРЯЕМ, ПОМЕЩАЕТСЯ ЛИ ВЕСЬ ТЕКСТ
    # =========================================================

    selected_font = None
    selected_lines = None

    for font_size in range(
        TEXT_FONT_SIZE,
        MIN_TEXT_FONT_SIZE - 1,
        -1
    ):

        test_font = ImageFont.truetype(
            "C:/Windows/Fonts/Arial.ttf",
            font_size
        )

        test_lines = build_lines(
            test_font
        )

        total_height = 0

        for label, value in test_lines:

            # Высота строки определяется
            # реальным шрифтом.

            bbox = draw.textbbox(
                (0, 0),
                "Ag",
                font=test_font
            )

            line_height = (
                bbox[3]
                - bbox[1]
            )

            total_height += (
                line_height
                + line_spacing
            )

        # Убираем последний spacing
        total_height -= line_spacing

        if total_height <= text_height:

            selected_font = test_font

            selected_lines = test_lines

            break

    # Если даже минимальный шрифт не влез,
    # используем его всё равно.
    if selected_font is None:

        selected_font = ImageFont.truetype(
            "C:/Windows/Fonts/Arial.ttf",
            MIN_TEXT_FONT_SIZE
        )

        selected_lines = build_lines(
            selected_font
        )

    # =========================================================
    # РИСУЕМ ТЕКСТ
    # =========================================================

    current_y = text_top

    for label, value in selected_lines:

        # -----------------------------------------------------
        # Определяем высоту строки
        # -----------------------------------------------------

        bbox = draw.textbbox(
            (0, 0),
            "Ag",
            font=selected_font
        )

        line_height = (
            bbox[3]
            - bbox[1]
        )

        # -----------------------------------------------------
        # Если это продолжение названия
        # -----------------------------------------------------

        if label == "":

            draw.text(
                (
                    text_left,
                    current_y
                ),
                value,
                fill="black",
                font=selected_font
            )

        else:

            # -------------------------------------------------
            # Рисуем название поля
            # -------------------------------------------------

            draw.text(
                (
                    text_left,
                    current_y
                ),
                label,
                fill="black",
                font=selected_font
            )

            label_bbox = draw.textbbox(
                (0, 0),
                label,
                font=selected_font
            )

            label_width = (
                label_bbox[2]
                - label_bbox[0]
            )

            value_x = (
                text_left
                + label_width
                + field_gap
            )

            # -------------------------------------------------
            # Значение
            # -------------------------------------------------

            draw.text(
                (
                    value_x,
                    current_y
                ),
                value,
                fill="black",
                font=selected_font
            )

        # -----------------------------------------------------
        # Следующая строка
        # -----------------------------------------------------

        current_y += (
            line_height
            + line_spacing
        )

    # =========================================================
    # ЧЁРНО-БЕЛЫЙ РЕЖИМ
    # =========================================================

    final = final.convert("1")

    # =========================================================
    # СОХРАНЯЕМ
    # =========================================================

    buf = BytesIO()

    final.save(
        buf,
        format="PNG"
    )

    buf.seek(0)

    return buf


def generate_qr_image_for_page(data):
    qr = generate_qr_image(data)
    # qr.add_data(data)
    # qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Сохраняем в байтовый буфер
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf

# --- Маршруты (URL) сайта ---
@app.route('/')
def index():
    """Главная страница со списком предметов."""
    items = load_items()
    return render_template('index.html', items=items)

@app.route('/scan')
def scan():
    """Страница для сканирования."""
    return render_template('scan.html', items=packing_list)

@app.route('/print_labels')
def print_labels():
    items = load_items()
    # Для каждого предмета генерируем QR-код и превращаем в base64
    for item in items:
        qr_buffer = generate_qr_image_for_page(item['id'])  
        qr_base64 = base64.b64encode(qr_buffer.getvalue()).decode('utf-8')
        item['qr_base64'] = f"data:image/png;base64,{qr_base64}"
    return render_template('print.html', items=items)


@app.route('/api/select_excel', methods=['POST'])
def select_excel():
    if 'excel_file' not in request.files:
        return jsonify({'error': 'Файл не выбран'}), 400
    file = request.files['excel_file']
    if file.filename == '':
        return jsonify({'error': 'Файл не выбран'}), 400
    if not file.filename.lower().endswith(('.xlsx', '.xls')):
        return jsonify({'error': 'Нужен .xlsx или .xls'}), 400

    filename = secure_filename(file.filename)
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(save_path)
    app.config['EXCEL_FILE'] = save_path

    return jsonify({'status': 'success', 'filename': filename})


@app.route('/api/add_item', methods=['POST'])
def add_item():
    """Добавляет новый предмет и возвращает его ID."""
    data = request.form
    product = data.get('product', '')
    placement_location = data.get('placement_location', '')
    current_count = data.get('current_count', 0)
    available_count = data.get('available_count', 0)
    analogue = data.get('analogue', '')
    # document = data.get('document', '')
    image_file = request.files.get('image')
    image_url = ''

    if image_file and image_file.filename:
        safe_name = secure_filename(image_file.filename)
        unique_name = f"{uuid.uuid4().hex}_{safe_name}"
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
        image_file.save(save_path)
        image_url = f"/uploads/{unique_name}"

    if not product:
        return jsonify({'error': 'Название предмета обязательно'}), 400

    excel_path = app.config.get('EXCEL_FILE')
    if not excel_path or not os.path.exists(excel_path):
        return jsonify({'error': 'Сначала загрузите Excel файл'}), 400
    
    items = load_items()
    new_id = str(uuid.uuid4())[:8]  # короткий уникальный ID
    new_item = {
        'id': new_id,
        'product': data.get('product', ''),
        'placement_location': data.get('placement_location', ''),
        'image': image_url,
        # 'document': data.get('document', ''),
        'current_count': data.get('current_count', 0),
        'available_count': data.get('available_count', 0),
        'analogue': data.get('analogue', '')}
        
    items.append(new_item)
    
    try:
        save_items(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'status': 'success', 'id': new_id})


@app.route('/api/add_to_list', methods=['POST'])
def add_to_list():
    """Заполнение укладочного листа"""
    data = request.json
    id = data.get('id')
    product = data.get('product', '')
    placement_location = data.get('placement_location', '')
    current_count = data.get('current_count', 0)
    available_count = data.get('available_count', 0)
    image = data.get('image', '')
    document = data.get('document', '')
    analogue = data.get('analogue', '')

    if not product:
        return jsonify({'error': 'Название предмета обязательно'}), 400

    new_item = {
        'id': id,
        'product': product,
        'placement_location': placement_location,
        'current_count': current_count,
        'available_count': available_count,
        'image': image,
        'document': document,
        'analogue': analogue
    }
    packing_list.append(new_item)
    return jsonify({'status': 'success', 'item': new_item})

@app.route('/api/get_item/<string:item_id>')
def get_item(item_id):
    """API для получения данных предмета по его ID."""
    items = load_items()
    for item in items:
        if item['id'] == item_id:
            return jsonify(item)
    return jsonify({'error': 'Item not found'}), 404

# --- Маршрут для печати ---
# ДЛЯ NINBOT НЕ ВИДИТ МОДУЛЬ
# @app.route('/api/print_item/<item_id>')
# def print_item(item_id):
#     items = load_items()

#     item = next((i for i in items if i['id'] == item_id), None)

#     if not item:
#         return jsonify({'error': 'Предмет не найден'}), 404

#     qr_buffer = generate_qr_image(item['id'])

#     # with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
#     #     tmp.write(qr_buffer.getvalue())
#     #     tmp_path = tmp.name

#     filename = f'qr_{item_id}.png'
#     filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
#     with open(filepath, 'wb') as f:
#         f.write(qr_buffer.getvalue())
    
#     # try:
#     #     command=[
#     #         "python", "-m", "NiimPrintX.cli", "print",
#     #         "-m", "d11",
#     #         "-d", "3",
#     #         "-n", "1",
#     #         "-r", "90",
#     #         "-i", tmp_path
#     #     ]

#     #     result = subprocess.run(command, capture_output=True, text=True, timeout=30)

#     #     if result.returncode == 0:
#     #         return jsonify({'status': 'success', 'message': f'Печать для {item["name"]} запущена'}), 200
#     #     else:
#     #         # Логируем ошибку для отладки
#     #         app.logger.error(f"Ошибка печати: {result.stderr}")
#     #         return jsonify({'error': 'Ошибка при отправке на печать'}), 500

#     # except subprocess.TimeoutExpired:
#     #     return jsonify({'error': 'Превышено время ожидания принтера'}), 500
#     # except Exception as e:
#     #     app.logger.error(f"Неизвестная ошибка: {str(e)}")
#     #     return jsonify({'error': 'Внутренняя ошибка сервера'}), 500
#     # finally:
#     #     # 6. Удаляем временный файл
#     #     if os.path.exists(tmp_path):
#     #         os.unlink(tmp_path)
#     try:
#         # Используем тот же интерпретатор Python, что и у Flask
#         python_exe = sys.executable

#         cmd = [
#             python_exe, '-m', 'NiimPrintX.NiimPrintX.cli', 'print',
#             '-m', 'd11',   
#             '-d', '3',       
#             '-n', '1',       
#             '-r', '90',     
#             '-i', filepath  
#         ]

#         result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

#         if result.returncode != 0:
#             app.logger.error(f"Ошибка печати: {result.stderr}")
#             return jsonify({'error': 'Ошибка печати', 'details': result.stderr}), 500

#         # (Опционально) удалить временный файл после успешной печати
#         # os.remove(filepath)
#         print("sss")
#         return jsonify({'message': 'Печать выполнена успешно'}), 200

#     except subprocess.TimeoutExpired:
#         return jsonify({'error': 'Таймаут печати (30 сек)'}), 500
#     except Exception as e:
#         app.logger.exception("Неожиданная ошибка при печати")
#         return jsonify({'error': str(e)}), 500


# niimprint_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'NiimPrintX', 'NiimPrintX'))
niimprint_root = os.path.abspath(os.path.join(os.path.dirname(__file__), 'NiimPrintX', 'NiimPrintX'))
if niimprint_root not in sys.path:
    sys.path.insert(0, niimprint_root)

@app.route('/api/print_item/<item_id>')
def print_item(item_id):
    items = load_items()
    item = next((i for i in items if i['id'] == item_id), None)
    if not item:
        return jsonify({'error': 'Предмет не найден'}), 404

    if not printer_lock.acquire(blocking=False):
        return jsonify({'error': 'Принтер занят. Дождитесь завершения печати.'}), 409
    try:
        qr_buffer = generate_qr_image_for_print(item['id'], item)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], f'qr_{uuid.uuid4().hex}.png')
        try:
            with open(filepath, 'wb') as f:
                f.write(qr_buffer.getvalue())
            from NiimPrintX.NiimPrintX.cli.command import niimbot_cli
            niimbot_cli.main(
                args=['print', '-m', 'b31', '-d', '3', '-n', '1', '-i', filepath],
                obj={}, standalone_mode=False,
            )
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)
        return jsonify({'status': 'success', 'message': 'Печать выполнена'}), 200
    except Exception as e:
        app.logger.exception("Ошибка печати")
        return jsonify({'error': 'Ошибка печати', 'details': str(e)}), 500
    finally:
        printer_lock.release()



# ДЛЯ ТЕСТА ЧЕРЕЗ БРАУЗЕР НА ДРУГОМ ПРИНТЕРЕ
# @app.route('/api/print_item/<item_id>')
# def print_item(item_id):
#     items = load_items()
#     item = next((i for i in items if i['id'] == item_id), None)
#     if not item:
#         return jsonify({'error': 'Предмет не найден'}), 404

#     # Генерируем QR как изображение
#     qr_buffer = generate_qr_image(item['id'])
#     qr_base64 = base64.b64encode(qr_buffer.getvalue()).decode('utf-8')
#     item['qr_base64'] = f"data:image/png;base64,{qr_base64}"
#     filename = f'qr_{item_id}.png'
#     # Сохранение в папку картинок qr.png
#     # filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
#     # with open(filepath, 'wb') as f:
#     #     f.write(qr_buffer.getvalue())
    
#     return render_template('print_item.html', item=item)


@app.route('/api/download_excel')
def download_excel():
    excel_path = app.config.get('EXCEL_FILE')
    # if os.path.exists(save_path):
    #     print("elf")
    #     os.remove(save_path)
    if not excel_path or not os.path.exists(excel_path):
        return "Файл не найден", 404
    return send_file(excel_path, as_attachment=True, download_name='warehouse_updated.xlsx')


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/api/packing/reset', methods=['POST'])
def reset_packing():
    packing_list.clear()
    return jsonify({'status': 'success'})

@app.route('/packing/print')
def print_packing():
    return render_template('print_packing.html', items=packing_list)


@app.route('/api/delete_item/<item_id>', methods=['DELETE'])
def delete_item(item_id):
    items = load_items()
    items = [item for item in items if item['id'] != item_id]
    try:
        save_items(items)
        return jsonify({'status': 'success', 'message': 'Предмет удален'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/edit_item/<item_id>', methods=['PUT'])
def edit_items(item_id):
    data = request.json
    items = load_items()

    # item_found = False
    # for item in items:
    #     if item['id'] == item_id:
    #         item['product'] = data.get('product', item.get('product', ''))
    #         item['placement_location'] = data.get('placement_location', item.get('placement_location', ''))
    #         item['current_count'] = data.get('current_count', item.get('current_count', 0))
    #         item['available_count'] = data.get('available_count', item.get('available_count', 0))
    #         item['analogue'] = data.get('analogue', item.get('analogue', ''))
    #         item_found = True
    #         break
    # if not item_found:
    #     return jsonify({'error': 'Предмет не найден'}), 404

    item = next((i for i in items if i['id'] == item_id), None)
    if item:
        item['product'] = data.get('product', item.get('product', ''))
        item['placement_location'] = data.get('placement_location', item.get('placement_location', ''))
        item['current_count'] = data.get('current_count', item.get('current_count', 0))
        item['available_count'] = data.get('available_count', item.get('available_count', 0))
        item['analogue'] = data.get('analogue', item.get('analogue', ''))
    else:
        return jsonify({'error': 'Предмет не найден'}), 404

    try:
        save_items(items)
        return jsonify({'status': 'success', 'message': 'Предмет обновлен'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Запуск сервера ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
