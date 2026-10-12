"""Read and update the selected Excel workbook, preserving its columns."""
import os
import pandas as pd
from flask import current_app as app


def load_items():
    """Загружает данные из Excel."""
    excel_path = app.config.get('EXCEL_FILE')
    if not excel_path or not os.path.exists(excel_path):
        return []
    df = pd.read_excel(excel_path, dtype={'id': str}, keep_default_na=False)
    if 'id' in df.columns:
        df['id'] = df['id'].astype(str).str.strip()
    return df.to_dict(orient='records')


def load_columns():
    """Возвращает заголовки выбранного Excel в исходном порядке."""
    excel_path = app.config.get('EXCEL_FILE')
    if not excel_path or not os.path.exists(excel_path):
        return []
    return list(pd.read_excel(excel_path, nrows=0).columns)


def save_items(items):
    """Сохраняет данные в Excel."""
    excel_path = app.config.get('EXCEL_FILE')
    if not excel_path:
        raise RuntimeError('Excel файл не выбран')
    # Preserve the header order and custom columns, including an empty workbook.
    columns = load_columns()
    df = pd.DataFrame(items, columns=columns)
    df.to_excel(excel_path, index=False)
