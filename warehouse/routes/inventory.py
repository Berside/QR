"""Inventory HTTP endpoints."""
import os
import uuid
from flask import current_app as app, request, jsonify, send_file, send_from_directory
from werkzeug.utils import secure_filename
from ..repository import load_items, load_columns, save_items


def select_excel():
    if 'excel_file' not in request.files:
        return (jsonify({'error': 'Файл не выбран'}), 400)
    file = request.files['excel_file']
    if file.filename == '':
        return (jsonify({'error': 'Файл не выбран'}), 400)
    if not file.filename.lower().endswith(('.xlsx', '.xls')):
        return (jsonify({'error': 'Нужен .xlsx или .xls'}), 400)
    filename = secure_filename(file.filename)
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(save_path)
    app.config['EXCEL_FILE'] = save_path
    return jsonify({'status': 'success', 'filename': filename})


def add_item():
    """Добавляет новый предмет и возвращает его ID."""
    data = request.form
    excel_path = app.config.get('EXCEL_FILE')
    if not excel_path or not os.path.exists(excel_path):
        return (jsonify({'error': 'Сначала загрузите Excel файл'}), 400)
    columns = load_columns()
    if not any((data.get(column, '').strip() for column in columns if column != 'id')):
        return (jsonify({'error': 'Заполните хотя бы одно поле'}), 400)
    image_file = request.files.get('image')
    image_url = ''
    if image_file and image_file.filename:
        safe_name = secure_filename(image_file.filename)
        unique_name = f'{uuid.uuid4().hex}_{safe_name}'
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
        image_file.save(save_path)
        image_url = f'/uploads/{unique_name}'
    items = load_items()
    new_id = str(uuid.uuid4())[:8]
    new_item = {column: data.get(column, '') for column in columns}
    if 'id' in columns:
        new_item['id'] = new_id
    if 'image' in columns:
        new_item['image'] = image_url
    items.append(new_item)
    try:
        save_items(items)
    except Exception as e:
        return (jsonify({'error': str(e)}), 500)
    return jsonify({'status': 'success', 'id': new_id})


def get_item(item_id):
    """API для получения данных предмета по его ID."""
    items = load_items()
    for index, item in enumerate(items):
        if item['id'] == item_id:
            # Excel row 1 contains column headings, so the first data row is 2.
            return jsonify(**item, _meta={
                'excel_row': index + 2,
                'item_number': index + 1,
            })
    return (jsonify({'error': 'Item not found'}), 404)


def delete_item(item_id):
    items = load_items()
    items = [item for item in items if item['id'] != item_id]
    try:
        save_items(items)
        return (jsonify({'status': 'success', 'message': 'Предмет удален'}), 200)
    except Exception as e:
        return (jsonify({'error': str(e)}), 500)


def edit_items(item_id):
    data = request.json
    items = load_items()
    item = next((i for i in items if i['id'] == item_id), None)
    if not item:
        return (jsonify({'error': 'Предмет не найден'}), 404)
    values = data.get('values', data)
    for column in load_columns():
        if column != 'id' and column in values:
            item[column] = values[column]
    try:
        save_items(items)
        return (jsonify({'status': 'success', 'message': 'Предмет обновлен'}), 200)
    except Exception as e:
        return (jsonify({'error': str(e)}), 500)


def download_excel():
    excel_path = app.config.get('EXCEL_FILE')
    if not excel_path or not os.path.exists(excel_path):
        return ('Файл не найден', 404)
    return send_file(excel_path, as_attachment=True, download_name='warehouse_updated.xlsx')


def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


def register(app):
    app.add_url_rule('/api/select_excel', view_func=select_excel, methods=['POST'])
    app.add_url_rule('/api/add_item', view_func=add_item, methods=['POST'])
    app.add_url_rule('/api/get_item/<string:item_id>', view_func=get_item, methods=['GET'])
    app.add_url_rule('/api/delete_item/<item_id>', view_func=delete_item, methods=['DELETE'])
    app.add_url_rule('/api/edit_item/<item_id>', view_func=edit_items, methods=['PUT'])
    app.add_url_rule('/api/download_excel', view_func=download_excel, methods=['GET'])
    app.add_url_rule('/uploads/<filename>', view_func=uploaded_file, methods=['GET'])
