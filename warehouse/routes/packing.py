"""Packing HTTP endpoints."""
from flask import current_app as app, request, jsonify, render_template


def scan():
    """Страница для сканирования."""
    return render_template('scan.html', items=app.extensions['packing_list'])


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
        return (jsonify({'error': 'Название предмета обязательно'}), 400)
    new_item = {
        'id': id,
        'product': product,
        'placement_location': placement_location,
        'current_count': current_count,
        'available_count': available_count,
        'image': image,
        'document': document,
        'analogue': analogue,
    }
    app.extensions['packing_list'].append(new_item)
    return jsonify({'status': 'success', 'item': new_item})


def reset_packing():
    app.extensions['packing_list'].clear()
    return jsonify({'status': 'success'})


def print_packing():
    return render_template('print_packing.html', items=app.extensions['packing_list'])


def register(app):
    app.add_url_rule('/scan', view_func=scan, methods=['GET'])
    app.add_url_rule('/api/add_to_list', view_func=add_to_list, methods=['POST'])
    app.add_url_rule('/api/packing/reset', view_func=reset_packing, methods=['POST'])
    app.add_url_rule('/packing/print', view_func=print_packing, methods=['GET'])
