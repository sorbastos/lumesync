"""Temas visuais. A preferência não faz parte da configuração de sincronização."""
import re
from PySide6.QtCore import QSettings

DARK_STYLE = """
QWidget { background: #111b23; color: #dbe6ed; font-family: 'Noto Sans', sans-serif; font-size: 13px; }
QLabel#brand { font-size: 23px; font-weight: 700; color: #70dbb7; }
QLabel#headline { font-size: 27px; font-weight: 650; }
QLabel#badge { background: #203e42; color: #8ce5ca; border-radius: 6px; padding: 7px 12px; font-size: 11px; }
QFrame#card { background: #1b2a36; border: 1px solid #2a3c49; border-radius: 10px; padding: 9px; }
QFrame#card QLabel { background: transparent; color: #adbfcd; }
QFrame#card QLabel#number { font-size: 30px; font-weight: 700; color: #f5f8fa; }
QPushButton { background: #243745; border: 1px solid #385264; padding: 10px 14px; border-radius: 6px; }
QPushButton:hover { background: #314a5d; }
QPushButton:disabled { color: #75838b; background: #1b2831; border-color: #253743; }
QPushButton#primary { background: #70dbb7; color: #102c29; border: none; font-weight: 700; }
QPushButton#primary:disabled { background: #294940; color: #839d94; }
QTabWidget::pane { border: 1px solid #2a3c49; border-radius: 5px; }
QTabBar::tab { padding: 11px 22px; color: #9cb2c2; }
QTabBar::tab:selected { color: #70dbb7; border-bottom: 2px solid #70dbb7; }
QTableWidget { border: none; background: #14212b; alternate-background-color: #182833; gridline-color: #233643; }
QHeaderView::section { background: #1e303e; border: none; padding: 10px; text-align: left; color: #a8bfce; }
QTableWidget::item { padding: 8px; }
QTableWidget::item:selected { background: #2e4a59; }
QLineEdit, QPlainTextEdit, QSpinBox, QComboBox { background: #162630; border: 1px solid #36505f; border-radius: 5px; padding: 7px; }
QLabel#footer { color: #859daa; font-size: 11px; }
"""

LIGHT_COLORS = {
    '#111b23': '#f6f8fb', '#dbe6ed': '#1b3040', '#70dbb7': '#00745a',
    '#203e42': '#dcefe8', '#8ce5ca': '#005742', '#1b2a36': '#ffffff',
    '#2a3c49': '#c8d4df', '#adbfcd': '#435b6b', '#f5f8fa': '#183449',
    '#243745': '#e7edf3', '#385264': '#9db1c1', '#314a5d': '#d6e3ed',
    '#75838b': '#697b89', '#1b2831': '#edf1f5', '#253743': '#ccd6df',
    '#102c29': '#ffffff', '#294940': '#d7e6df', '#839d94': '#526d60',
    '#9cb2c2': '#425d70', '#14212b': '#ffffff', '#182833': '#f0f5f9',
    '#233643': '#d4dfe8', '#1e303e': '#e2eaf1', '#a8bfce': '#304f65',
    '#2e4a59': '#c8e5db', '#162630': '#ffffff', '#36505f': '#9db1c1',
    '#859daa': '#526b7e',
}
LIGHT_STYLE = re.sub(r'#[0-9a-f]{6}', lambda match: LIGHT_COLORS[match.group()], DARK_STYLE)


def settings():
    return QSettings('LumeSync', 'Appearance')


def load_theme():
    value = settings().value('theme', 'dark')
    return value if value in ('dark', 'light') else 'dark'


def save_theme(theme):
    if theme not in ('dark', 'light'):
        raise ValueError('Tema inválido')
    store = settings()
    store.setValue('theme', theme)
    store.sync()
    if store.status() != QSettings.Status.NoError:
        raise OSError('Não foi possível salvar o tema nas preferências do usuário.')


def stylesheet(theme):
    return LIGHT_STYLE if theme == 'light' else DARK_STYLE
