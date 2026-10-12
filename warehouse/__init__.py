"""Flask application factory."""
from pathlib import Path
from threading import Lock

from flask import Flask

from .config import Config


def create_app(config=None):
    app = Flask(__name__, instance_path=str(Config.INSTANCE_PATH))
    app.config.from_object(Config)
    if config:
        app.config.update(config)

    Path(app.config['UPLOAD_FOLDER']).mkdir(parents=True, exist_ok=True)
    app.extensions['packing_list'] = []
    app.extensions['printer_lock'] = Lock()

    from .routes import editor, inventory, packing, pages, printing
    from . import labels, repository

    for routes in (inventory, packing, pages, printing):
        routes.register(app)
    editor.register(
        app, labels.label_background_image,
        repository.load_columns, repository.load_items,
    )
    return app
