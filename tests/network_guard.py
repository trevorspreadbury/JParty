"""Keep the test suite offline.

``install()`` wraps Python's ``socket.connect`` and Qt's
``QNetworkAccessManager.get`` so any attempt to reach a host other than this
machine is refused and recorded. The ``conftest.py`` autouse fixture fails the
test that made the attempt, even when it happened on a background thread that
swallowed the error.
"""

import os
import socket
import threading

from PyQt6.QtCore import QUrl
from PyQt6.QtNetwork import QNetworkAccessManager

LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
# Nothing listens on the discard port, so a blocked Qt request fails quickly.
BLOCKED_QT_URL = "http://127.0.0.1:9/blocked-by-network-guard"

_violations = []
_lock = threading.Lock()


class NetworkAccessBlocked(OSError):
    """Raised when a test tries to open a connection to a remote host."""


def _is_local(host: object) -> bool:
    """Return whether ``host`` names this machine."""
    host = str(host).strip("[]").lower()
    return host in LOCAL_HOSTS or host.startswith("127.")


def _record(target: str) -> None:
    """Remember a blocked attempt so the running test can fail.

    A background thread may outlive the test that started it, so the message
    names the test that started the thread as well.
    """
    started_by = getattr(threading.current_thread(), "_started_by_test", None)
    if started_by:
        target = f"{target} (thread started by {started_by})"
    with _lock:
        _violations.append(target)


def take_violations() -> list:
    """Return and clear the blocked attempts recorded so far."""
    with _lock:
        violations = list(_violations)
        _violations.clear()
    return violations


def install() -> None:
    """Block remote connections for the rest of the test session."""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_get = QNetworkAccessManager.get
    original_thread_start = threading.Thread.start

    def check_address(sock: socket.socket, address: object) -> None:
        # UDP "connect" sends nothing; ``BuzzerController.localip`` uses it.
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            return
        if sock.type == socket.SOCK_DGRAM:
            return
        host = address[0] if isinstance(address, tuple) else address
        if not _is_local(host):
            _record(f"socket connect to {address!r}")
            raise NetworkAccessBlocked(f"Tests must not connect to {address!r}")

    def guarded_connect(self: socket.socket, address: object) -> None:
        check_address(self, address)
        return original_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: object) -> int:
        check_address(self, address)
        return original_connect_ex(self, address)

    def guarded_get(self: QNetworkAccessManager, request: object) -> object:
        url = request.url()
        if url.scheme() not in ("file", "qrc", "data") and not _is_local(url.host()):
            _record(f"QNetworkAccessManager.get({url.toString()})")
            request.setUrl(QUrl(BLOCKED_QT_URL))
        return original_get(self, request)

    def tagged_thread_start(self: threading.Thread) -> None:
        # Threads started by a background thread keep the original test name.
        self._started_by_test = getattr(
            threading.current_thread(), "_started_by_test", None
        ) or os.environ.get("PYTEST_CURRENT_TEST")
        original_thread_start(self)

    threading.Thread.start = tagged_thread_start
    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    QNetworkAccessManager.get = guarded_get
