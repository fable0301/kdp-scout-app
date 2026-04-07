import traceback
from abc import abstractmethod
from PyQt6.QtCore import QThread, pyqtSignal


class BaseWorker(QThread):
    """Base worker thread with progress reporting and cancellation support.

    Signals:
        progress(int, int) - (current, maximum) progress values
        status(str) - status text updates
        log(str) - log messages
        finished_with_result(object) - emitted on success with result data
        error(str) - emitted on failure with error message
    """

    progress = pyqtSignal(int, int)
    status = pyqtSignal(str)
    log = pyqtSignal(str)
    finished_with_result = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancelled = False

    def cancel(self):
        """Request cancellation of the running task."""
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def run(self):
        """Execute the worker task with error handling."""
        self._cancelled = False
        try:
            result = self.run_task()
            if not self._cancelled:
                self.finished_with_result.emit(result)
            else:
                self.status.emit("Cancelled")
                self.finished_with_result.emit(None)
        except Exception as e:
            tb = traceback.format_exc()
            self.log.emit(f"ERROR: {tb}")
            self.error.emit(str(e))

    @abstractmethod
    def run_task(self):
        """Override this method with the actual work to perform.

        Returns:
            The result object to emit via finished_with_result signal.
        """
        raise NotImplementedError

    def progress_callback(self, current: int, total: int, message: str = ""):
        """Convenience callback for passing to business logic functions."""
        self.progress.emit(current, total)
        if message:
            self.status.emit(message)
