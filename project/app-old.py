import os
import uuid
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

packing_list = []

# EXCEL_FILE = 'warehouse.xlsx'

# --- Функции для работы с Excel (как с базой данных) ---
def load_items():
    """Загружает данные из Excel."""
    excel_path = app.config.get('EXCEL_FILE')
    
    if not excel_path or not os.path.exists(excel_path):
        return []
    df = pd.read_excel(excel_path, dtype={'id': str}, keep_default_na=False)
    df['id'] = df['id'].str.strip()
    return df.to_dict(orient='records')

def save_items(items):
    """Сохраняет данные в Excel."""
    excel_path = app.config.get('EXCEL_FILE')
    if not excel_path:
        raise RuntimeError('Excel файл не выбран')
    df = pd.DataFrame(items)
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


# --- Функция для генерации QR-кода ---
def generate_qr_image_for_print(data, item):
    """
    Генерирует QR-код в виде PNG (байтовый поток).
    :param data: строка, которая будет закодирована (обычно ID предмета)
    :return: BytesIO объект с PNG-изображением
    """

    qr = generate_qr_image(data)

    # qr = qrcode.QRCode(
    #     version=1,
    #     error_correction=qrcode.constants.ERROR_CORRECT_L,
    #     box_size=10,
    #     border=4,
    # )
    # qr = qrcode.QRCode(
    #     version=1,
    #     error_correction=qrcode.constants.ERROR_CORRECT_L,
    #     box_size=4,
    #     border=4,
    # )
    # qr.add_data(data)
    # qr.make(fit=True)
    # img = qr.make_image(fill_color="black", back_color="white")
    img = qr.make_image()
    img = img.convert("RGB")
    

    target_width = int(30 / 25.4 * 203)
    target_height = int(14 / 25.4 * 203)
    qr_w, qr_h = img.size

    max_qr_side = min(target_height, target_width)

    final = Image.new("RGB", (target_width, target_height), "white")
    # final = Image.new("RGB", (target_width, target_height), (255,255,255))
    
    draw = ImageDraw.Draw(final)

    x_offset = (target_width - max_qr_side + 7)
    y_offset = (target_height - max_qr_side)
    final.paste(img, (x_offset, y_offset, x_offset+qr_w, y_offset+qr_h))

    # text_x = target_height + 2 + 4
    text_x = 6 
    text_width = target_width - text_x - 2

    text_y_start = 30

    # product_wr = "\n".join(wrap(item['product'], width=14))

    # lines = [
    #     f"ID: {item['id']}",
    #     f"Изд.: {product_wr}",
    #     f"Кол-во: {item['available_count']}",
    # ]

    product_wr = wrap(item['product'], width=14)
    lines = [f"ID: {item['id']}"]
    if product_wr:
        lines.append(f"Изд.: {product_wr[0]}")
        for line in product_wr[1:]:
            lines.append(f"    {line}")
    lines.append(f"Кол-во: {item['available_count']}")

    font_size = 14
    font = ImageFont.truetype("C:/Windows/Fonts/Arial.ttf", font_size)
    line_height = 13
    for i, line in enumerate(lines):
        y = text_y_start + i * line_height + 4
        draw.text((text_x, y), line, fill="black", font=font)
    
    draw.rectangle([(2, 10), (target_width-2, target_height-9)], outline="black", width=1)
    final = final.convert("1")
    # final.show()
    
    # Сохраняем в байтовый буфер
    buf = BytesIO()
    final.save(buf, format='PNG')
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

    # Генерируем QR
    qr_buffer = generate_qr_image_for_print(item['id'], item)
    filename = f'qr_{item_id}.png'
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    # filepath = 'C:\\Users\\EvGen\\Desktop\\QR\\project\\' + filepath
    with open(filepath, 'wb') as f:
        f.write(qr_buffer.getvalue())

    try:
        # Импортируем CLI-функцию
        from NiimPrintX.NiimPrintX.cli.command import niimbot_cli

        # text = "\\u041f\\u0435\\u0447\\u0430\\u0442\\u044c \\u0432\\u044b\\u043f\\u043e\\u043b\\u043d\\u0435\\u043d\\u0430 \\u0443\\u0441\\u043f\\u0435\\u0448\\u043d\\u043e"
        # decoded = text.encode('latin1').decode('unicode_escape')
        # print('!!!!',decoded)

        # Сохраняем оригинальные аргументы командной строки
        original_argv = sys.argv

        sys.argv = [
            'niimbot_cli',  
            'print',
            '-m', 'd11',
            '-d', '3',
            '-n', '1',
            '--ho', '-8',
            '-r', '90',
            '-i', filepath
        ]

        try:
            # Вызываем CLI. obj={} как в __main__.py
            niimbot_cli(obj={})
           
        except SystemExit as e:
            if e.code != 0:
                raise Exception(f"CLI вернул код ошибки {e.code}")
        finally:
            sys.argv = original_argv
            # app.logger.info(f"Печать для {item_id} выполнена успешно")
            # return jsonify({f"message": "Печать выполнена успешно"}), 200
            return jsonify({'status': 'success', 'message': 'Печать выполнена'}), 200

    except Exception as e:
        app.logger.error(f"Ошибка печати: {str(e)}")
        traceback.print_exc()
        return jsonify({f"error": 'Ошибка печати', 'details': str(e)}), 500



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