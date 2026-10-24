from __future__ import annotations

import copy
import sys
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QColor, QPixmap, QPainter, QPalette
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
    QFormLayout, QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QFileDialog,
    QMessageBox, QCheckBox, QSystemTrayIcon, QMenu, QAbstractItemView, QScrollArea)

from .themes import DARK_STYLE, load_theme, save_theme, stylesheet
from . import __version__
from .config import DATA, load, save, build
from .drive import authorize
from .presentation import STATES, error_help, pin_for_entry, offline_state

LABELS = {"equal": "Em dia", "upload": "Enviar", "download": "Receber", "conflict": "Conflito",
          "deletion": "Decidir ausência", "blocked": "Bloqueado"}


class Worker(QThread):
    completed = Signal(object)
    failed = Signal(str)
    message = Signal(str)
    planned = Signal(object)
    transferring = Signal(object)

    def __init__(self, config, job, actions=None, resolutions=None, client=None):
        super().__init__()
        self.config, self.job = copy.deepcopy(config), job
        self.actions, self.resolutions, self.client = actions, resolutions, client
        self.stop_event = threading.Event()
        self.relative = ''
        self.entry = None
        self.retry_paths = None
        self.release_path = None

    def run(self):
        engine = None
        try:
            if self.job == "auth":
                authorize(Path(self.client), DATA / "google-token.json", self.message.emit)
                self.completed.emit({"authorized": True})
                return
            if self.config.get('access_mode') == 'online':
                from .online import OnlineDrive
                controller = OnlineDrive(load())
                offline_actions = None
                errors = []
                if self.job == 'sync':
                    controller.start()
                elif self.job == 'online-reconnect':
                    controller.reconnect()
                if self.job == 'release-offline':
                    controller.release_file(self.release_path)
                    self.message.emit('Cópia offline removida; arquivo mantido no Drive: ' + self.release_path)
                if self.job == 'pin':
                    path = controller.pin(self.entry, self.relative)
                    self.message.emit('Cópia offline selecionada: ' + path)
                if controller.config.get('pins'):
                    engine = build(controller.offline_config())
                    engine.provider.cancelled = self.stop_event.is_set
                    engine.provider.progress = self.message.emit
                    plan = self.actions if self.actions is not None else engine.plan()
                    self.planned.emit({"actions": plan, "config": controller.config})
                    if self.job in ('pin', 'offline-sync', 'offline-resolve'):
                        if self.retry_paths is not None:
                            plan = [a for a in plan if a.path in self.retry_paths]
                        engine.apply(plan, self.resolutions, self.message.emit, self.stop_event.is_set,
                                     continue_on_error=True, transfer=self.transferring.emit)
                        errors = engine.errors
                    offline_actions = engine.plan()
                directory = self.relative.rpartition('/')[0] if self.job == 'pin' else self.relative
                entries = controller.entries(directory)
                self.completed.emit({'online': True, 'entries': entries, 'relative': directory,
                                     'mounted': controller.mounted(), 'config': controller.config,
                                     'offline_actions': offline_actions, 'errors': errors})
                return
            engine = build(self.config)
            engine.provider.cancelled = self.stop_event.is_set
            engine.provider.progress = self.message.emit
            actions = self.actions if self.actions is not None else engine.plan()
            self.planned.emit(actions)
            if self.retry_paths is not None:
                actions = [a for a in actions if a.path in self.retry_paths]
            if self.job in ("sync", "resolve"):
                engine.apply(actions, self.resolutions, self.message.emit, self.stop_event.is_set, continue_on_error=True, transfer=self.transferring.emit)
                actions = engine.plan()
            self.completed.emit({'actions': actions, 'notices': engine.provider.notices,
                                 'warnings': getattr(engine.provider, 'warnings', []),
                                 'errors': getattr(engine, 'errors', [])})
        except InterruptedError:
            self.completed.emit({'actions': [], 'notices': [], 'paused': True})
        except Exception as error:
            if engine:
                engine.state.log('', 'scan-error', str(error))
            self.failed.emit(str(error))
        finally:
            if engine:
                engine.state.close()


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = load()
        self.theme = load_theme()
        self.worker = None
        self.force_exit = False
        self.actions = []
        self.current_relative = ''
        self.online_entries = []
        self.offline_actions = []
        self.preview_config = None
        self.file_errors = {}
        self.active_transfer = None
        self.retry_context = None
        self.last_request = None
        self.setWindowTitle("Lume Sync")
        self.resize(1160, 790)
        self.setMinimumSize(850, 640)
        self.setWindowIcon(app_icon())
        outer = QWidget()
        self.setCentralWidget(outer)
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(30, 24, 30, 20)
        layout.setSpacing(18)
        header = QHBoxLayout()
        brand = QLabel("◈  Lume Sync")
        brand.setObjectName("brand")
        header.addWidget(brand)
        header.addStretch()
        self.badge = QLabel("DEMONSTRAÇÃO" if self.config["mode"] == "demo" else "GOOGLE DRIVE")
        self.badge.setObjectName("badge")
        header.addWidget(self.badge)
        layout.addLayout(header)
        self.status = QLabel("Seus arquivos, nos dois lugares.")
        self.status.setObjectName("headline")
        layout.addWidget(self.status)
        self.subtitle = QLabel("Analise as pastas para ver o que precisa ser enviado ou recebido.")
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.subtitle)
        cards = QHBoxLayout()
        self.cards = {}
        self.card_titles = {}
        for key, title in [("equal", "Em dia"), ("upload", "Para enviar"), ("download", "Para receber"), ("attention", "Precisam de você")]:
            frame = QFrame(); frame.setObjectName("card")
            content = QVBoxLayout(frame)
            number = QLabel("—"); number.setObjectName("number")
            content.addWidget(number)
            title_label = QLabel(title); content.addWidget(title_label)
            self.card_titles[key] = title_label
            self.cards[key] = number; cards.addWidget(frame)
        layout.addLayout(cards)
        bar = QHBoxLayout()
        self.scan_button = QPushButton("Analisar pastas")
        self.scan_button.clicked.connect(lambda: self.start("scan"))
        self.sync_button = QPushButton("Sincronizar prévia")
        self.sync_button.setObjectName("primary")
        self.sync_button.clicked.connect(self.sync_preview)
        self.sync_button.setEnabled(False)
        self.pause_button = QPushButton("Pausar")
        self.pause_button.clicked.connect(self.pause)
        self.pause_button.setEnabled(False)
        self.auto = QCheckBox("Sincronizar periodicamente")
        self.auto.toggled.connect(self.monitor)
        for widget in (self.scan_button, self.sync_button, self.pause_button, self.auto):
            bar.addWidget(widget)
        bar.addStretch()
        open_button = QPushButton("Abrir pasta")
        open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.config["local"])))
        bar.addWidget(open_button)
        layout.addLayout(bar)
        self.retry_button = QPushButton('Tentar novamente')
        self.retry_button.clicked.connect(self.retry_failed)
        self.retry_button.setVisible(False)
        layout.addWidget(self.retry_button)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        files = QWidget(); file_layout = QVBoxLayout(files)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Arquivo", "Estado", "Tamanho", "Detalhes"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        file_layout.addWidget(self.table)
        resolutions = QHBoxLayout()
        self.conflict_label = QLabel('Conflito selecionado:')
        resolutions.addWidget(self.conflict_label)
        self.local_button = QPushButton("Usar versão local")
        self.remote_button = QPushButton("Usar versão da nuvem")
        self.local_button.clicked.connect(lambda: self.resolve("local"))
        self.remote_button.clicked.connect(lambda: self.resolve("remote"))
        self.local_button.setEnabled(False); self.remote_button.setEnabled(False)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        self.table.cellDoubleClicked.connect(self.open_online_entry)
        resolutions.addWidget(self.local_button); resolutions.addWidget(self.remote_button); resolutions.addStretch()
        self.release_button = QPushButton('Liberar cópia offline')
        self.release_button.clicked.connect(lambda: self.release_selected(False))
        self.release_button.setEnabled(False)
        resolutions.addWidget(self.release_button)
        file_layout.addLayout(resolutions)
        online_bar = QHBoxLayout()
        self.back_button = QPushButton('Voltar à pasta anterior')
        self.back_button.clicked.connect(self.online_back)
        self.pin_button = QPushButton('Manter neste computador')
        self.pin_button.clicked.connect(self.pin_selected)
        self.reconnect_button = QPushButton('Reconectar / aplicar .lumeignore')
        self.reconnect_button.clicked.connect(self.reconnect_online)
        self.offline_open_button = QPushButton('Abrir cópias offline')
        self.offline_open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.config.get('offline_local', ''))))
        for widget in (self.back_button, self.pin_button, self.offline_open_button, self.reconnect_button): online_bar.addWidget(widget)
        self.online_bar_widgets = [self.back_button, self.pin_button, self.offline_open_button, self.reconnect_button]
        online_bar.addStretch(); file_layout.addLayout(online_bar)
        self.tabs.addTab(files, "Arquivos")
        offline_page = QWidget(); offline_layout = QVBoxLayout(offline_page)
        offline_layout.addWidget(QLabel('Itens marcados têm cópias em Offline. O Lume sincroniza enquanto estiver aberto; conflitos aguardam sua escolha.'))
        self.offline_table = QTableWidget(0, 3)
        self.offline_table.setHorizontalHeaderLabels(['Cópia offline', 'Estado', 'Motivo'])
        self.offline_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.offline_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.offline_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.offline_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        offline_layout.addWidget(self.offline_table)
        buttons = QHBoxLayout()
        refresh = QPushButton('Sincronizar cópias offline agora'); refresh.clicked.connect(lambda: self.start('offline-sync'))
        buttons.addWidget(refresh)
        for choice, text in [('local', 'Usar cópia local'), ('remote', 'Usar versão da nuvem')]:
            button = QPushButton(text); button.clicked.connect(lambda checked=False, option=choice: self.resolve_offline(option)); buttons.addWidget(button)
        self.offline_release_button = QPushButton('Liberar cópia offline')
        self.offline_release_button.clicked.connect(lambda: self.release_selected(True))
        buttons.addWidget(self.offline_release_button)
        offline_layout.addLayout(buttons)
        self.offline_tab_index = self.tabs.addTab(offline_page, 'Cópias offline')
        self.activity = QPlainTextEdit(); self.activity.setReadOnly(True)
        self.tabs.addTab(self.activity, "Atividade")
        self.issues = QPlainTextEdit(); self.issues.setReadOnly(True)
        self.issues.setPlaceholderText('Aqui aparecem os arquivos que precisam de atenção e os itens mantidos somente na nuvem.')
        self.tabs.addTab(self.issues, 'Pendências')
        settings = QWidget(); form = QFormLayout(settings)
        form.setContentsMargins(20, 20, 20, 20); form.setSpacing(15)
        self.mode = QComboBox(); self.mode.addItems(["Demonstração · duas pastas", "Google Drive"])
        self.mode.setCurrentIndex(0 if self.config["mode"] == "demo" else 1)
        self.theme_selector = QComboBox()
        self.theme_selector.addItem('Escuro', 'dark')
        self.theme_selector.addItem('Claro', 'light')
        self.theme_selector.setCurrentIndex(1 if self.theme == 'light' else 0)
        self.theme_selector.currentIndexChanged.connect(self.change_theme)
        form.addRow('Aparência', self.theme_selector)
        form.addRow("Conta", self.mode)
        self.local = QLineEdit(self.config["local"])
        form.addRow("Pasta local", self.folder_field(self.local))
        self.remote = QLineEdit(self.config["remote"])
        self.remote_field = self.folder_field(self.remote)
        form.addRow("Nuvem de demonstração", self.remote_field)
        self.remote_field.setEnabled(self.mode.currentIndex() == 0)
        self.mode.currentIndexChanged.connect(lambda index: self.remote_field.setEnabled(index == 0))
        self.root_id = QLineEdit(self.config.get("root_id", "root"))
        form.addRow("ID da pasta no Drive", self.root_id)
        hint = QLabel('Use “root” para Meu Drive ou o ID no final do endereço de uma pasta do Google Drive.')
        hint.setWordWrap(True); form.addRow("", hint)
        self.interval = QSpinBox(); self.interval.setRange(15, 3600); self.interval.setSuffix(" segundos")
        self.interval.setValue(self.config.get("interval", 60)); form.addRow("Intervalo", self.interval)
        self.ignores = QPlainTextEdit("\n".join(self.config["ignores"])); self.ignores.setMaximumHeight(130)
        form.addRow("Ignorar · uma regra por linha", self.ignores)
        connect = QPushButton("Conectar Google Drive…")
        connect.clicked.connect(self.connect_google)
        form.addRow("", connect)
        self.save_button = QPushButton("Salvar configurações")
        self.save_button.clicked.connect(self.save_settings)
        form.addRow("", self.save_button)
        edit_ignore = QPushButton('Abrir .lumeignore no editor')
        edit_ignore.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.config.get('ignore_file', str(Path(__file__).resolve().parent.parent / '.lumeignore')))))
        form.addRow('', edit_ignore)
        note = QLabel('No modo sob demanda, use Manter neste computador para escolher cópias offline.\nAs exclusões do .lumeignore são aplicadas à montagem ao reconectar o Drive.')
        note.setWordWrap(True); form.addRow("", note)
        settings_scroll = QScrollArea(); settings_scroll.setWidgetResizable(True); settings_scroll.setWidget(settings)
        self.tabs.addTab(settings_scroll, 'Configurações')
        footer = QLabel(f"Lume Sync {__version__}  •  Cópias locais + Google Drive  •  Exclusões automáticas desativadas")
        footer.setObjectName("footer"); layout.addWidget(footer)
        self.timer = QTimer(self); self.timer.timeout.connect(self.tick)
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(app_icon(), self)
            self.tray.setToolTip("Lume Sync")
            menu = QMenu()
            show = menu.addAction("Abrir Lume Sync"); show.triggered.connect(self.showNormal)
            pause = menu.addAction("Pausar sincronização"); pause.triggered.connect(self.pause)
            quit_action = menu.addAction("Sair"); quit_action.triggered.connect(self.request_quit)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
            self.tray.show()
        self.configure_access_controls()
        self.apply_theme()
        self.log('Pronto. ' + ('Drive sob demanda; cópias offline somente dos itens marcados.' if self.is_online() else 'Modo de cópia local.'))

    def apply_theme(self):
        application = QApplication.instance()
        light = self.theme == 'light'
        palette = QPalette()
        colors = {
            QPalette.ColorRole.Window: '#f6f8fb' if light else '#111b23',
            QPalette.ColorRole.WindowText: '#1b3040' if light else '#dbe6ed',
            QPalette.ColorRole.Base: '#ffffff' if light else '#14212b',
            QPalette.ColorRole.AlternateBase: '#f0f5f9' if light else '#182833',
            QPalette.ColorRole.Text: '#1b3040' if light else '#dbe6ed',
            QPalette.ColorRole.Button: '#e7edf3' if light else '#243745',
            QPalette.ColorRole.ButtonText: '#1b3040' if light else '#dbe6ed',
            QPalette.ColorRole.Highlight: '#00745a' if light else '#2e4a59',
            QPalette.ColorRole.HighlightedText: '#ffffff',
            QPalette.ColorRole.ToolTipBase: '#ffffff' if light else '#1b2a36',
            QPalette.ColorRole.ToolTipText: '#1b3040' if light else '#dbe6ed',
        }
        for role, color in colors.items():
            palette.setColor(role, QColor(color))
        application.setPalette(palette)
        application.setStyleSheet(stylesheet(self.theme))
        if not self.is_online():
            for row, action in enumerate(getattr(self, 'rows', [])):
                item = self.table.item(row, 1)
                if item:
                    item.setForeground(self.state_color(action.kind))

    def state_color(self, kind):
        attention = kind in ('conflict', 'deletion', 'blocked')
        if self.theme == 'light':
            return QColor('#895000' if attention else '#00664f')
        return QColor('#ffbf69' if attention else '#70dbb7')

    def change_theme(self):
        selected = self.theme_selector.currentData()
        try:
            save_theme(selected)
        except OSError as error:
            self.theme_selector.blockSignals(True)
            self.theme_selector.setCurrentIndex(1 if self.theme == 'light' else 0)
            self.theme_selector.blockSignals(False)
            QMessageBox.warning(self, 'Aparência', str(error))
            return
        self.theme = selected
        self.apply_theme()

    def is_online(self):
        return self.config.get('access_mode') == 'online'

    def configure_access_controls(self):
        online = self.is_online()
        self.release_button.setVisible(online)
        self.scan_button.setText('Atualizar lista online' if online else 'Analisar pastas')
        self.sync_button.setText('Conectar no Dolphin' if online else 'Sincronizar prévia')
        self.sync_button.setEnabled(online)
        self.auto.setVisible(not online)
        self.pause_button.setVisible(not online)
        self.local_button.setVisible(not online); self.remote_button.setVisible(not online)
        self.conflict_label.setVisible(not online)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        for widget in self.online_bar_widgets: widget.setVisible(online)
        self.tabs.setTabVisible(self.offline_tab_index, online)
        if online:
            self.card_titles['equal'].setText('Acesso ao Drive')
            self.card_titles['upload'].setText('Cache temporário · alvo')
            self.card_titles['download'].setText('Cópias offline selecionadas')
            self.table.setToolTip('Na nuvem: acesso sob demanda, podendo usar cache temporário. Offline: cópia sincronizada na pasta Offline.')
            self.timer.start(60000)
            ignore = Path(self.config.get('ignore_file', ''))
            if ignore.is_file(): self.ignores.setPlainText(ignore.read_text())

    def completed_online(self, result):
        self.config = result['config']
        self.current_relative = result['relative']
        self.online_entries = result['entries']
        self.cards['equal'].setText('Ativo' if result['mounted'] else 'Desligado')
        self.cards['upload'].setText('2 GiB')
        self.cards['download'].setText(str(len(self.config.get('pins', []))))
        errors = result.get('errors', [])
        if result.get('offline_actions') is not None:
            self.offline_actions = result['offline_actions']
        elif not self.config.get('pins'):
            self.offline_actions = []
        self.update_errors(errors)
        self.render_online_rows()
        self.render_offline_rows()
        attention = sum(a.kind in ('conflict', 'deletion', 'blocked') for a in self.offline_actions) + len(self.file_errors)
        self.cards['attention'].setText(str(attention))
        self.show_errors()
        self.status.setText('Seu Drive, sem cópia integral no computador' if result['mounted'] else 'Conecte o Drive para acessar pelo Dolphin')
        self.subtitle.setText(f"{len(self.online_entries)} itens nesta pasta · /{self.current_relative} · Offline em {self.config.get('offline_local', '')}")
        self.back_button.setEnabled(bool(self.current_relative))
        if self.file_errors:
            self.status.setText('1 arquivo com erro' if len(self.file_errors) == 1 else f'{len(self.file_errors)} arquivos com erro')
            self.subtitle.setText('Veja o motivo em Pendências e clique em Tentar novamente.')
        self.log('Lista online atualizada. Nenhum download em massa foi solicitado.')

    def render_online_rows(self):
        self.table.setRowCount(len(self.online_entries))
        for row, entry in enumerate(self.online_entries):
            pin = pin_for_entry(entry, self.current_relative, self.config.get('pins', []), self.config.get('offline_excludes', []))
            state = offline_state(pin['path'], self.offline_actions, self.file_errors, self.active_transfer) if pin else 'Na nuvem · sob demanda'
            label = entry['Name'] + (' · ID ' + entry.get('ID', '')[-8:] if entry.get('_duplicate') else '')
            size = 'Pasta' if entry.get('IsDir') else f"{max(0, entry.get('Size', 0))/1024/1024:.1f} MiB"
            detail = 'Nome duplicado; abre no navegador' if entry.get('_duplicate') else 'Clique duas vezes para abrir'
            if pin:
                error = next((message for path, message in self.file_errors.items()
                              if path == pin['path'] or path.startswith(pin['path'].rstrip('/') + '/')), None)
                if error:
                    title, guidance = error_help(error)
                    detail = title + '. ' + guidance
            for col, value in enumerate([label, state, size, detail]):
                self.table.setItem(row, col, QTableWidgetItem(value))

    def render_offline_rows(self):
        self.offline_table.setRowCount(len(self.offline_actions))
        for row, action in enumerate(self.offline_actions):
            state = offline_state(action.path, [action], self.file_errors, self.active_transfer)
            reason = self.file_errors.get(action.path, action.reason)
            for col, text in enumerate([action.path, state, reason]):
                self.offline_table.setItem(row, col, QTableWidgetItem(text))

    def update_errors(self, errors):
        # A metadata refresh must not erase a failed transfer.
        job = (self.last_request or {}).get('job')
        if job == 'release-offline':
            self.file_errors.pop(self.last_request.get('release_path'), None)
        if job in ('sync', 'resolve', 'pin', 'offline-sync', 'offline-resolve'):
            if self.worker and self.worker.retry_paths is not None:
                for path in self.worker.retry_paths:
                    self.file_errors.pop(path, None)
            elif self.worker and self.worker.actions is not None:
                for action in self.worker.actions:
                    self.file_errors.pop(action.path, None)
            else:
                self.file_errors.clear()
        self.file_errors.update({e['path']: e['message'] for e in errors})
        if self.file_errors:
            self.retry_context = {'job': 'offline-sync' if self.is_online() else 'sync',
                                  'retry_paths': set(self.file_errors)}
        else:
            self.retry_context = None
        self.retry_button.setVisible(bool(self.retry_context))

    def show_errors(self, warnings=()):
        lines = list(warnings)
        for path, message in self.file_errors.items():
            title, help_text = error_help(message)
            lines.append(f'{path}\n{title}. {help_text}\nDetalhe: {message}\n')
        self.issues.setPlainText('\n'.join(lines))

    def receive_plan(self, actions):
        self.active_transfer = None
        if isinstance(actions, dict):
            self.config = actions['config']
            actions = actions['actions']
        if self.is_online():
            self.offline_actions = actions
            self.render_offline_rows()
            self.render_online_rows()

    def receive_transfer(self, event):
        self.active_transfer = event
        self.status.setText(('Baixando: ' if event['kind'] == 'download' else 'Enviando: ') + event['path'])
        if self.is_online():
            self.render_offline_rows()
            self.render_online_rows()
        else:
            for row, action in enumerate(getattr(self, 'rows', [])):
                if action.path == event['path']:
                    self.table.setItem(row, 1, QTableWidgetItem('Baixando…' if event['kind'] == 'download' else 'Enviando…'))

    def retry_failed(self):
        if not self.retry_context or self.worker and self.worker.isRunning():
            return
        context = copy.deepcopy(self.retry_context)
        # Rebuild the plan; never replay a stale conflict resolution.
        if 'retry_paths' in context:
            self.start(context['job'], retry_paths=context['retry_paths'])
        else:
            self.current_relative = context['relative']
            self.selected_online_entry = context['entry']
            if context.get('release_path'):
                self.start(context['job'], release_path=context['release_path'])
            else:
                self.start(context['job'], client=context.get('client'))

    def open_online_entry(self, row, column):
        if not self.is_online() or not 0 <= row < len(self.online_entries): return
        entry = self.online_entries[row]
        relative = (self.current_relative + '/' if self.current_relative else '') + entry['Name']
        if entry.get('_duplicate'):
            QDesktopServices.openUrl(QUrl('https://drive.google.com/' + ('drive/folders/' if entry.get('IsDir') else 'file/d/') + entry.get('ID', '')))
        elif entry.get('IsDir'):
            self.current_relative = relative; self.start('scan')
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.config['local']) / relative)))

    def reconnect_online(self):
        if QMessageBox.question(self, 'Aplicar exclusões', 'Feche os arquivos abertos na pasta online antes de reconectar. As alterações pendentes ficam no cache para envio. Reconectar agora?') == QMessageBox.StandardButton.Yes:
            self.start('online-reconnect')

    def online_back(self):
        self.current_relative = self.current_relative.rpartition('/')[0]
        self.start('scan')

    def pin_selected(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self.online_entries): return
        self.selected_online_entry = self.online_entries[row]
        rid = self.selected_online_entry.get('ID')
        selected_pin = pin_for_entry(self.selected_online_entry, self.current_relative, self.config.get('pins', []), self.config.get('offline_excludes', []))
        if selected_pin and any(pin['remote_id'] == rid for pin in self.config.get('pins', [])):
            if QMessageBox.question(self, 'Parar de manter offline', 'Parar a sincronização offline deste item? As cópias locais serão preservadas.') == QMessageBox.StandardButton.Yes:
                self.config['pins'] = [pin for pin in self.config['pins'] if pin['remote_id'] != rid]
                save(self.config)
                self.start('scan')
            return
        if QMessageBox.question(self, 'Manter neste computador', 'Baixar este item e manter uma cópia sincronizada na pasta Offline? Pastas incluem todos os seus arquivos não ignorados.') == QMessageBox.StandardButton.Yes:
            self.start('pin')

    def release_selected(self, offline=False):
        if self.worker and self.worker.isRunning():
            return
        if offline:
            row = self.offline_table.currentRow()
            if not 0 <= row < len(self.offline_actions):
                QMessageBox.information(self, 'Selecione um arquivo', 'Selecione um arquivo na lista de cópias offline.')
                return
            path = self.offline_actions[row].path
        else:
            row = self.table.currentRow()
            if not 0 <= row < len(self.online_entries):
                return
            entry = self.online_entries[row]
            pin = pin_for_entry(entry, self.current_relative, self.config.get('pins', []), self.config.get('offline_excludes', []))
            if not pin or entry.get('IsDir'):
                return
            path = pin['path']
        answer = QMessageBox.question(self, 'Liberar cópia offline',
            f'Remover somente a cópia offline de {path}?\n\n'
            'O arquivo continuará no Google Drive e não será baixado novamente até você marcar Manter neste computador. '
            'A remoção só será feita se a cópia estiver igual à nuvem. Feche o arquivo antes de continuar.')
        if answer == QMessageBox.StandardButton.Yes:
            self.start('release-offline', release_path=path)

    def resolve_offline(self, choice):
        row = self.offline_table.currentRow()
        if not 0 <= row < len(self.offline_actions): return
        action = self.offline_actions[row]
        if action.kind not in ('conflict', 'deletion'): return
        if choice == 'local' and action.local is None or choice == 'remote' and action.remote is None: return
        if QMessageBox.question(self, 'Resolver cópia offline', f'Usar a versão {choice} de {action.path}?') == QMessageBox.StandardButton.Yes:
            self.start('offline-resolve', [action], {action.path: choice})

    def folder_field(self, field):
        widget = QWidget(); line = QHBoxLayout(widget); line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(field); button = QPushButton("Escolher…")
        button.clicked.connect(lambda: self.pick_folder(field)); line.addWidget(button)
        return widget

    def pick_folder(self, field):
        selected = QFileDialog.getExistingDirectory(self, "Escolher pasta", field.text())
        if selected:
            field.setText(selected)

    def log(self, text):
        from datetime import datetime
        line = datetime.now().strftime('%Y-%m-%d %H:%M:%S') + '  ' + text
        self.activity.appendPlainText(line)
        try:
            import os
            DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(DATA, 0o700)
            path = DATA / 'activity.log'
            if path.exists() and path.stat().st_size > 5 * 1024 * 1024:
                os.replace(path, DATA / 'activity.previous.log')
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, 'a') as handle:
                handle.write(line + '\n')
        except OSError:
            pass

    def save_settings(self):
        self.pause()
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Transferência em andamento", "Aguarde a operação atual terminar para salvar.")
            return
        config = {**self.config, "mode": "demo" if self.mode.currentIndex() == 0 else "drive", "local": self.local.text().strip(),
                  "remote": self.remote.text().strip(), "root_id": self.root_id.text().strip(),
                  "interval": self.interval.value(), "ignores": [p.strip() for p in self.ignores.toPlainText().splitlines() if p.strip()]}
        if not config["local"] or config["mode"] == "demo" and not config["remote"]:
            QMessageBox.warning(self, "Pasta necessária", "Informe as pastas antes de salvar."); return
        try:
            if config.get('ignore_file'):
                Path(config['ignore_file']).write_text(self.ignores.toPlainText() + '\n', encoding='utf-8')
            if config['mode'] == 'demo': config['access_mode'] = 'offline'
            save(config)
            self.config = config; self.actions = []; self.table.setRowCount(0); self.preview_config = None
            for card in self.cards.values(): card.setText("—")
            self.sync_button.setEnabled(False)
            self.badge.setText("DEMONSTRAÇÃO" if config["mode"] == "demo" else "GOOGLE DRIVE")
            self.status.setText("Configurações salvas")
            self.file_errors.clear()
            self.retry_context = None
            self.retry_button.setVisible(False)
            self.configure_access_controls()
            self.log('Configurações salvas. As exclusões online são aplicadas ao reconectar o Drive.')
        except Exception as error:
            self.failure(str(error))

    def start(self, job, actions=None, resolutions=None, client=None, retry_paths=None, release_path=None):
        if self.worker and self.worker.isRunning(): return
        self.last_request = {'job': job, 'relative': self.current_relative,
                             'entry': copy.deepcopy(getattr(self, 'selected_online_entry', None)), 'client': client, 'release_path': release_path}
        if retry_paths is not None:
            self.last_request['retry_paths'] = set(retry_paths)
        self.retry_button.setEnabled(False)
        self.worker = Worker(self.config, job, actions, resolutions, client)
        self.worker.retry_paths = retry_paths
        self.worker.release_path = release_path
        self.release_button.setEnabled(False)
        self.offline_release_button.setEnabled(False)
        self.worker.planned.connect(self.receive_plan)
        self.worker.transferring.connect(self.receive_transfer)
        self.worker.relative = self.current_relative
        self.worker.entry = getattr(self, 'selected_online_entry', None)
        if job == 'pin':
            self.worker.relative = (self.current_relative + '/' if self.current_relative else '') + self.worker.entry['Name']
        self.worker.message.connect(self.log)
        self.worker.completed.connect(self.completed)
        self.worker.failed.connect(self.failure)
        self.worker.finished.connect(self.idle)
        self.scan_button.setEnabled(False); self.sync_button.setEnabled(False); self.save_button.setEnabled(False)
        self.local_button.setEnabled(False); self.remote_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.status.setText("Conectando ao Google…" if job == "auth" else "Analisando…" if job == "scan" else "Sincronizando…")
        self.worker.start()

    def sync_preview(self):
        if self.is_online():
            self.start('sync')
            return
        if self.preview_config != self.config:
            QMessageBox.information(self, "Nova análise necessária", "Analise as pastas antes de sincronizar."); return
        self.start("sync", self.actions)

    def completed(self, result):
        self.active_transfer = None
        if result.get('online'):
            self.completed_online(result)
            return
        if result.get('paused'):
            self.status.setText('Análise pausada')
            self.preview_config = None
            self.log('Análise pausada. Clique em Analisar pastas para continuar.')
            return
        if result.get("authorized"):
            self.status.setText("Google Drive conectado")
            self.log("Autorização concluída. Escolha Google Drive nas configurações e salve.")
            return
        self.actions = result["actions"]
        self.preview_config = copy.deepcopy(self.config)
        counts = {kind: sum(a.kind == kind for a in self.actions) for kind in LABELS}
        for key in ("equal", "upload", "download"):
            self.cards[key].setText(str(counts[key]))
        warnings = result.get('warnings', [])
        errors = result.get('errors', [])
        self.update_errors(errors)
        self.show_errors(warnings)
        attention = counts["conflict"] + counts["deletion"] + counts["blocked"] + len(warnings) + len(self.file_errors)
        self.cards["attention"].setText(str(attention))
        rows = sorted(self.actions, key=lambda a: (a.kind == "equal", a.path))
        self.rows = rows
        self.table.setRowCount(len(rows))
        for i, action in enumerate(rows):
            size = (action.local or action.remote).size
            size_label = f"{size / 1024 / 1024:.1f} MB" if size >= 1024 * 1024 else f"{size / 1024:.1f} KB"
            for col, text in enumerate([action.path, ('Erro · tentar novamente' if action.path in self.file_errors else STATES[action.kind]), size_label, self.file_errors.get(action.path, action.reason)]):
                item = QTableWidgetItem(text)
                if col == 1: item.setForeground(self.state_color(action.kind))
                self.table.setItem(i, col, item)
        for notice in result.get("notices", []): self.log(notice)
        self.status.setText("Sua decisão é necessária" if attention else "Pronto para sincronizar" if counts["upload"] + counts["download"] else "Tudo em dia")
        self.subtitle.setText(f'{len(rows)} arquivos analisados · {self.config["local"]}')
        self.log(f'Análise: {counts["upload"]} envios, {counts["download"]} recebimentos, {attention} pendências.')

    def idle(self):
        self.active_transfer = None
        if self.is_online():
            self.render_online_rows()
            self.render_offline_rows()
        self.retry_button.setEnabled(True)
        self.offline_release_button.setEnabled(True)
        self.scan_button.setEnabled(True); self.save_button.setEnabled(True)
        self.sync_button.setEnabled(self.is_online() or self.preview_config == self.config and bool(self.actions))
        self.pause_button.setEnabled(self.auto.isChecked())
        self.selection_changed()

    def failure(self, text):
        self.auto.setChecked(False)
        self.preview_config = None
        self.status.setText("A operação precisa de atenção")
        title, help_text = error_help(text)
        self.subtitle.setText(title + '. ' + help_text)
        self.issues.setPlainText(title + '\n' + help_text + '\n\nDetalhe: ' + text)
        self.retry_context = copy.deepcopy(self.last_request)
        if self.retry_context and self.retry_context['job'] in ('resolve', 'offline-resolve'):
            self.retry_context['job'] = 'scan'
        self.retry_button.setVisible(bool(self.retry_context))
        self.active_transfer = None
        self.log("Erro: " + text)

    def selection_changed(self):
        if self.is_online():
            row = self.table.currentRow()
            valid = 0 <= row < len(self.online_entries)
            self.pin_button.setEnabled(valid and not (self.worker and self.worker.isRunning()))
            entry = self.online_entries[row] if valid else None
            selected_pin = pin_for_entry(entry, self.current_relative, self.config.get('pins', []), self.config.get('offline_excludes', [])) if entry else None
            self.release_button.setEnabled(bool(selected_pin and not entry.get('IsDir') and not (self.worker and self.worker.isRunning())))
            pinned = valid and any(pin['remote_id'] == self.online_entries[row].get('ID') for pin in self.config.get('pins', []))
            self.pin_button.setText('Parar de manter offline' if pinned else 'Manter neste computador')
            return
        row = self.table.currentRow()
        action = self.rows[row] if hasattr(self, "rows") and 0 <= row < len(self.rows) else None
        allowed = bool(action and action.kind in ("conflict", "deletion") and not (self.worker and self.worker.isRunning()))
        self.local_button.setEnabled(allowed and action.local is not None if action else False)
        self.remote_button.setEnabled(allowed and action.remote is not None if action else False)

    def resolve(self, choice):
        row = self.table.currentRow()
        if row < 0: return
        action = self.rows[row]
        destination = "nuvem" if choice == "local" else "pasta local"
        answer = QMessageBox.question(self, "Confirmar versão", f"Usar a versão {'local' if choice == 'local' else 'da nuvem'} de {action.path}?\nEla substituirá o conteúdo na {destination}, caso exista.")
        if answer == QMessageBox.StandardButton.Yes:
            self.start("resolve", [action], {action.path: choice})

    def monitor(self, enabled):
        if enabled:
            self.timer.start(self.config.get("interval", 60) * 1000)
            self.pause_button.setEnabled(True)
            self.log("Monitoramento ativado. Conflitos e exclusões aguardam sua decisão.")
            self.tick()
        else:
            self.timer.stop()

    def tick(self):
        if self.is_online():
            if self.config.get('pins'): self.start('offline-sync')
        else:
            self.start('sync')

    def pause(self):
        self.auto.setChecked(False); self.timer.stop()
        if self.worker and self.worker.isRunning():
            self.worker.stop_event.set()
            self.log("Pausa solicitada; a transferência atual será concluída.")
        else:
            self.pause_button.setEnabled(False)
            self.log("Sincronização periódica pausada.")

    def connect_google(self):
        if self.worker and self.worker.isRunning(): return
        client, _ = QFileDialog.getOpenFileName(self, "Credenciais OAuth · aplicativo para computador", "", "JSON (*.json)")
        if client: self.start("auth", client=client)

    def request_quit(self):
        self.force_exit = True
        if self.worker and self.worker.isRunning():
            self.worker.finished.connect(self.close)
        self.close()

    def closeEvent(self, event):
        if self.is_online() and self.tray and not self.force_exit:
            self.hide()
            event.ignore()
            return
        self.pause()
        if self.worker and self.worker.isRunning():
            self.status.setText("Aguarde a operação atual para sair")
            event.ignore()
        else:
            if self.tray: self.tray.hide()
            event.accept()


def app_icon():
    pixmap = QPixmap(64, 64); pixmap.fill(QColor("#132b30"))
    painter = QPainter(pixmap); painter.setPen(QColor("#70dbb7"))
    font = painter.font(); font.setPixelSize(44); painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "◈"); painter.end()
    return QIcon(pixmap)


STYLE = DARK_STYLE


def main():
    monitor = '--monitor' in sys.argv
    app = QApplication([arg for arg in sys.argv if arg != '--monitor'])
    app.setApplicationName("Lume Sync")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = Window(); window.show()
    if window.is_online():
        QTimer.singleShot(0, lambda: window.start('sync'))
    elif monitor:
        QTimer.singleShot(0, lambda: window.auto.setChecked(True))
    sys.exit(app.exec())


if __name__ == "__main__": main()
