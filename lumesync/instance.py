"""Uma janela por perfil: novas aberturas ativam o processo já existente."""
from __future__ import annotations

import fcntl
import hashlib
import os
from pathlib import Path
import stat
import time

from PySide6.QtCore import QObject, QStandardPaths, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    activation_requested = Signal()

    def __init__(self, profile: Path, runtime_dir=None, parent=None):
        super().__init__(parent)
        base = Path(runtime_dir or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.RuntimeLocation)) / 'lumesync'
        base.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = base.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError('A pasta de controle do aplicativo não é segura.')
        base.chmod(0o700)
        key = hashlib.sha256(str(Path(profile).resolve()).encode()).hexdigest()[:24]
        self.socket_path = str(base / (key + '.sock'))
        self.lock_path = base / (key + '.lock')
        self.lock_fd = None
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._accept)
        self.buffers = {}

    def start(self, timeout_ms=3000):
        """True para a primeira instância; False após ativar a existente."""
        if self.lock_fd is not None:
            return True
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            if self._activate(timeout_ms):
                return False
            raise RuntimeError('O Lume Sync já está aberto ou iniciando. Aguarde alguns segundos e tente abrir novamente.')
        except BaseException:
            os.close(fd)
            raise
        self.lock_fd = fd
        # O lock pertence a este processo; um socket restante só pode ser antigo.
        QLocalServer.removeServer(self.socket_path)
        if not self.server.listen(self.socket_path):
            self.close()
            raise RuntimeError('Não foi possível preparar a abertura única do Lume Sync.')
        return True

    def _activate(self, timeout_ms):
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            socket = QLocalSocket()
            socket.connectToServer(self.socket_path)
            if socket.waitForConnected(100):
                socket.write(b'show\n')
                socket.flush()
                response = b''
                while len(response) < 64 and time.monotonic() < deadline:
                    remaining = max(1, int((deadline - time.monotonic()) * 1000))
                    if not socket.bytesAvailable() and not socket.waitForReadyRead(remaining):
                        break
                    response += bytes(socket.readAll())
                    if b'\n' in response:
                        break
                socket.abort()
                return response == b'ok\n'
            socket.abort()
            time.sleep(.03)
        return False

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self.buffers[socket] = b''
            socket.readyRead.connect(lambda client=socket: self._read(client))
            socket.disconnected.connect(lambda client=socket: self._discard(client))
            if socket.bytesAvailable():
                self._read(socket)

    def _read(self, socket):
        data = self.buffers.get(socket, b'') + bytes(socket.readAll())
        if len(data) > 64 or b'\n' in data and data != b'show\n':
            socket.abort()
            return
        self.buffers[socket] = data
        if data == b'show\n':
            self.activation_requested.emit()
            socket.write(b'ok\n')
            socket.flush()
            socket.disconnectFromServer()

    def _discard(self, socket):
        self.buffers.pop(socket, None)
        socket.deleteLater()

    def close(self):
        if self.lock_fd is None:
            return
        for socket in list(self.buffers):
            socket.abort()
        self.server.close()
        QLocalServer.removeServer(self.socket_path)
        fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
        os.close(self.lock_fd)
        self.lock_fd = None
