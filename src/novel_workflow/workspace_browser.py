from __future__ import annotations

import os
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QHBoxLayout, QLineEdit, QMessageBox, QPushButton, QTabWidget,
    QTextBrowser, QToolButton, QVBoxLayout, QWidget,
)

_WEBENGINE_ALLOWED = (
    os.environ.get("NOVELWORKFLOW_DISABLE_WEBENGINE", "").strip().lower()
    not in {"1", "true", "yes"}
    and os.environ.get("QT_QPA_PLATFORM", "").strip().lower() != "offscreen"
)

try:
    if not _WEBENGINE_ALLOWED:
        raise ImportError("Qt WebEngine disabled")
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    QWebEngineView = None


_START_PAGE = """
<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8">
<style>
html,body{height:100%;margin:0}
body{display:grid;place-items:center;background:#11141a;color:#a1a8b3;
font-family:"Segoe UI","Noto Sans Thai UI",sans-serif}
main{text-align:center;max-width:580px;padding:32px}
h1{color:#f1f3f5;font-size:28px;margin:0 0 12px}
p{font-size:16px;line-height:1.7}
.icon{font-size:60px;margin-bottom:14px}
</style>
</head>
<body><main><div class="icon">🌐</div><h1>Browser</h1>
<p>ใส่ URL ในช่องด้านบนเพื่อเปิดเว็บไซต์<br>
กด + เพื่อเปิดหลายแท็บภายในโปรแกรม</p></main></body>
</html>
"""


if QWebEngineView is not None:
    class WorkspaceWebView(QWebEngineView):
        def __init__(self, owner, parent=None):
            super().__init__(parent)
            self.owner = owner

        def createWindow(self, _window_type):
            return self.owner.new_tab(select=True)
else:
    WorkspaceWebView = None


class BrowserTabs(QWidget):
    """Tabbed embedded browser. Offscreen tests fall back to QTextBrowser."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.back = QToolButton()
        self.back.setText("←")
        self.forward = QToolButton()
        self.forward.setText("→")
        self.reload = QToolButton()
        self.reload.setText("↻")
        self.address = QLineEdit()
        self.address.setPlaceholderText("ใส่ URL ที่นี่…")
        self.go = QPushButton("Go")

        navigation = QHBoxLayout()
        navigation.setContentsMargins(0, 0, 0, 0)
        navigation.setSpacing(4)
        navigation.addWidget(self.back)
        navigation.addWidget(self.forward)
        navigation.addWidget(self.reload)
        navigation.addWidget(self.address, 1)
        navigation.addWidget(self.go)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(True)
        self.tabs.tabBar().setUsesScrollButtons(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._sync_address)

        add = QToolButton()
        add.setText("+")
        add.setToolTip("แท็บใหม่")
        add.clicked.connect(lambda: self.new_tab(select=True))
        self.tabs.setCornerWidget(add, Qt.TopRightCorner)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(navigation)
        layout.addWidget(self.tabs, 1)

        self.back.clicked.connect(lambda: self._call_current("back"))
        self.forward.clicked.connect(lambda: self._call_current("forward"))
        self.reload.clicked.connect(lambda: self._call_current("reload"))
        self.go.clicked.connect(self.navigate)
        self.address.returnPressed.connect(self.navigate)

        self.new_tab(select=True)

    def _call_current(self, name):
        view = self.tabs.currentWidget()
        method = getattr(view, name, None)
        if callable(method):
            method()

    def _make_view(self):
        if WorkspaceWebView is not None:
            view = WorkspaceWebView(self)
            view.titleChanged.connect(lambda title, v=view: self._set_title(v, title))
            view.urlChanged.connect(lambda url, v=view: self._url_changed(v, url))
            return view

        view = QTextBrowser()
        view.setOpenExternalLinks(False)
        view.setProperty("workspaceUrl", "about:blank")
        view.setHtml(
            "<div style='font-family:Segoe UI;padding:40px;text-align:center'>"
            "<h2>Browser</h2><p>WebEngine ถูกปิดในโหมดทดสอบ</p></div>"
        )
        return view

    def new_tab(self, url: str | QUrl | None = None, title="แท็บใหม่", select=True):
        view = self._make_view()
        index = self.tabs.addTab(view, title)
        if select:
            self.tabs.setCurrentIndex(index)

        if WorkspaceWebView is not None:
            if url and str(url) not in {"", "about:blank"}:
                view.setUrl(url if isinstance(url, QUrl) else QUrl(str(url)))
            else:
                view.setHtml(_START_PAGE, QUrl("about:blank"))
        else:
            value = url.toString() if isinstance(url, QUrl) else str(url or "about:blank")
            view.setProperty("workspaceUrl", value)

        return view

    def close_tab(self, index):
        if self.tabs.count() == 1:
            view = self.tabs.widget(0)
            if WorkspaceWebView is not None:
                view.setHtml(_START_PAGE, QUrl("about:blank"))
            else:
                view.setProperty("workspaceUrl", "about:blank")
            self.tabs.setTabText(0, "แท็บใหม่")
            self.address.clear()
            return

        widget = self.tabs.widget(index)
        self.tabs.removeTab(index)
        widget.deleteLater()

    @staticmethod
    def normalized_url(text: str) -> QUrl | None:
        text = text.strip()
        if not text:
            return None
        parsed = urlparse(text)
        if not parsed.scheme:
            text = "https://" + text
            parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        return QUrl(text)

    def navigate(self):
        url = self.normalized_url(self.address.text())
        if url is None:
            QMessageBox.warning(
                self, "URL ไม่ถูกต้อง", "กรุณาใส่ URL แบบ http:// หรือ https://"
            )
            return
        self.open_url(url, new_tab=False)

    def open_url(self, url: str | QUrl, title=None, new_tab=True):
        qurl = url if isinstance(url, QUrl) else self.normalized_url(str(url))
        if qurl is None:
            raise ValueError("รองรับเฉพาะ URL แบบ http และ https")

        if new_tab:
            return self.new_tab(qurl, title or "กำลังโหลด…", select=True)

        view = self.tabs.currentWidget()
        if WorkspaceWebView is not None:
            view.setUrl(qurl)
        else:
            view.setProperty("workspaceUrl", qurl.toString())
            view.setHtml(
                "<div style='font-family:Segoe UI;padding:32px'>"
                f"<h3>{qurl.toString()}</h3>"
                "<p>WebEngine ถูกปิดในโหมดทดสอบ</p></div>"
            )
        self.address.setText(qurl.toString())
        return view

    def _set_title(self, view, title):
        index = self.tabs.indexOf(view)
        if index >= 0:
            clean = (title or "แท็บใหม่").strip()
            self.tabs.setTabText(
                index, clean[:28] + ("…" if len(clean) > 28 else "")
            )

    def _url_changed(self, view, url):
        if self.tabs.currentWidget() is view:
            text = url.toString()
            self.address.setText("" if text == "about:blank" else text)

    def _sync_address(self, _index):
        view = self.tabs.currentWidget()
        if view is None:
            self.address.clear()
            return
        if WorkspaceWebView is not None:
            text = view.url().toString()
        else:
            text = str(view.property("workspaceUrl") or "about:blank")
        self.address.setText("" if text == "about:blank" else text)

    def urls(self) -> list[str]:
        result = []
        for index in range(self.tabs.count()):
            view = self.tabs.widget(index)
            if WorkspaceWebView is not None:
                value = view.url().toString() or "about:blank"
            else:
                value = str(view.property("workspaceUrl") or "about:blank")
            result.append(value)
        return result or ["about:blank"]

    def restore(self, urls, current_index=0):
        while self.tabs.count():
            widget = self.tabs.widget(0)
            self.tabs.removeTab(0)
            widget.deleteLater()

        for value in urls or ["about:blank"]:
            self.new_tab(value if value != "about:blank" else None, select=False)

        self.tabs.setCurrentIndex(
            max(0, min(int(current_index or 0), self.tabs.count() - 1))
        )
