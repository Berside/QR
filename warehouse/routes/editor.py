"""Label editor pages and template API."""
import uuid
from pathlib import Path

from flask import jsonify, render_template, request, send_file

from ..label_editor import (
    BODY, HEIGHT, WIDTH, STORE_LOCK, read_store, render,
    validate_template, write_store,
)


def register(app, background, load_columns, load_items):
    app.config.setdefault('LABEL_TEMPLATES_FILE', str(Path(app.instance_path) / 'label_templates.json'))

    @app.get('/label-editor')
    def label_editor():
        return render_template('label_editor.html')

    @app.get('/api/label-templates')
    def label_templates():
        return jsonify(**read_store(app), columns=load_columns(), body=BODY, width=WIDTH, height=HEIGHT)

    @app.post('/api/label-templates')
    def save_label_template():
        if request.content_length and request.content_length > 8_000_000:
            return jsonify(error='Шаблон слишком большой'), 413
        payload = request.get_json(silent=True)
        try:
            template = validate_template(payload)
            with STORE_LOCK:
                store = read_store(app)
                key = payload.get('id') or uuid.uuid4().hex
                if not isinstance(key, str) or (key not in store['templates'] and payload.get('id')):
                    raise ValueError('Шаблон не найден')
                if len(store['templates']) >= 100 and key not in store['templates']:
                    raise ValueError('Достигнут лимит: 100 шаблонов')
                store['templates'][key] = template
                store['active'] = key
                write_store(app, store)
            return jsonify(id=key)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

    @app.post('/api/label-templates/active')
    def select_label_template():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify(error='Неверный запрос'), 400
        key = payload.get('id')
        with STORE_LOCK:
            store = read_store(app)
            if key is not None and (not isinstance(key, str) or key not in store['templates']):
                return jsonify(error='Шаблон не найден'), 404
            store['active'] = key
            write_store(app, store)
        return jsonify(status='success')

    @app.delete('/api/label-templates/<string:key>')
    def delete_label_template(key):
        with STORE_LOCK:
            store = read_store(app)
            template = store['templates'].get(key)
            if template is None:
                return jsonify(error='Шаблон не найден'), 404
            del store['templates'][key]
            if store['active'] == key:
                store['active'] = None
            write_store(app, store)
        return jsonify(status='success', message=f'Шаблон «{template["name"]}» удалён')

    @app.get('/api/label-templates/background')
    def label_background():
        return send_file(background(), mimetype='image/png')

    @app.post('/api/label-templates/preview')
    def preview_label_template():
        if request.content_length and request.content_length > 8_000_000:
            return jsonify(error='Шаблон слишком большой'), 413
        try:
            template = validate_template(request.get_json(silent=True))
            items = load_items()
            item = items[0] if items else {'id': 'DEMO-001', 'product': 'Пример изделия', 'ШИБФ': '123.456', 'available_count': 10}
            return send_file(render(template, item, background()), mimetype='image/png')
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
