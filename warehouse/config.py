"""Paths are anchored to the project, independent of the working directory."""
from pathlib import Path


class Config:
    ROOT_PATH = Path(__file__).resolve().parent.parent
    INSTANCE_PATH = ROOT_PATH / 'instance'
    UPLOAD_FOLDER = str(INSTANCE_PATH / 'uploads')
    LABEL_TEMPLATES_FILE = str(INSTANCE_PATH / 'label_templates.json')
    # The user selects a workbook in the UI, as before.
    EXCEL_FILE = None
