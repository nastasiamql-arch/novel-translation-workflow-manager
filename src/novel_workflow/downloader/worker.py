from PySide6.QtCore import QThread, Signal
import time


class DownloaderWorker(QThread):
    progress = Signal(int, int, str, int, int, int)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            result = self.operation(_Cancellation(self), self._progress)
            if self.isInterruptionRequested():
                self.cancelled.emit()
            else:
                self.completed.emit(result)
        except InterruptedError:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    def _progress(self, current, total, chapter, result):
        self.progress.emit(current, total, chapter.title, result.downloaded, result.skipped, result.failed)


class _Cancellation:
    def __init__(self, worker): self.worker = worker
    def is_set(self): return self.worker.isInterruptionRequested()
    def wait(self, seconds):
        deadline = time.monotonic() + seconds
        while not self.is_set() and time.monotonic() < deadline:
            time.sleep(min(0.1, deadline - time.monotonic()))
        return self.is_set()
