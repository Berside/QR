"""Printing HTTP endpoints."""
import base64
import os
import uuid
from flask import current_app as app, jsonify, render_template
from ..repository import load_items, load_columns
from ..labels import LABEL_COLUMNS, generate_qr_image_for_print


def print_labels():
    items = load_items()
    columns = load_columns()
    label_columns = [column for column in LABEL_COLUMNS if column in columns]
    for item in items:
        try:
            qr_buffer = generate_qr_image_for_print(item['id'], item, columns)
            qr_base64 = base64.b64encode(qr_buffer.getvalue()).decode('utf-8')
            item['qr_base64'] = f'data:image/png;base64,{qr_base64}'
        except ValueError as exc:
            item['label_error'] = str(exc)
    return render_template('print.html', items=items, label_columns=label_columns)


def print_item(item_id):
    items = load_items()
    item = next((i for i in items if i['id'] == item_id), None)
    if not item:
        return (jsonify({'error': 'Предмет не найден'}), 404)
    if not app.extensions['printer_lock'].acquire(blocking=False):
        return (jsonify({'error': 'Принтер занят. Дождитесь завершения печати.'}), 409)
    try:
        qr_buffer = generate_qr_image_for_print(item['id'], item, load_columns())
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], f'qr_{uuid.uuid4().hex}.png')
        try:
            with open(filepath, 'wb') as f:
                f.write(qr_buffer.getvalue())
            from ..vendor.niimprintx.cli.command import niimbot_cli
            niimbot_cli.main(
                args=['print', '-m', 'b31', '-d', '3', '-n', '1', '-i', filepath],
                obj={}, standalone_mode=False,
            )
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)
        return (jsonify({'status': 'success', 'message': 'Печать выполнена'}), 200)
    except ValueError as e:
        return (jsonify({'error': str(e)}), 400)
    except Exception as e:
        app.logger.exception('Ошибка печати')
        return (jsonify({'error': 'Ошибка печати', 'details': str(e)}), 500)
    finally:
        app.extensions['printer_lock'].release()


def register(app):
    app.add_url_rule('/print_labels', view_func=print_labels, methods=['GET'])
    app.add_url_rule('/api/print_item/<item_id>', view_func=print_item, methods=['GET'])
