"""Pages HTTP endpoints."""
from flask import render_template
from ..repository import load_items, load_columns


def index():
    """Главная страница со списком предметов."""
    items = load_items()
    columns = load_columns()
    return render_template('index.html', items=items, columns=columns)


def register(app):
    app.add_url_rule('/', view_func=index, methods=['GET'])
