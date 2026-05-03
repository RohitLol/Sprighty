"""Tiny QThreadPool helper for running blocking calls off the main thread."""

from PySide6.QtCore import QObject, QRunnable, Signal, QThreadPool


class _Signals(QObject):
    done = Signal(object)   # emits whatever the callable returns (or None on exception)


class Worker(QRunnable):
    """Run fn(*args, **kwargs) on the global thread pool.

    The ``signals.done`` signal is emitted on the worker thread after fn
    returns. PySide6 queues the delivery to any slot connected from the main
    thread automatically (Qt.AutoConnection), so it is safe to update UI
    widgets inside on_done callbacks.
    """

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.signals   = _Signals()
        self._fn       = fn
        self._args     = args
        self._kwargs   = kwargs
        self.setAutoDelete(True)

    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception:
            result = None
        self.signals.done.emit(result)


def run_async(fn, *args, on_done=None, **kwargs) -> Worker:
    """Submit fn(*args, **kwargs) to the global thread pool.

    Parameters
    ----------
    fn       : callable to run in the background
    *args    : positional arguments forwarded to fn
    on_done  : optional callable(result) called (on main thread) when fn finishes
    **kwargs : keyword arguments forwarded to fn

    Returns the Worker instance (useful if you need to keep a reference).
    """
    w = Worker(fn, *args, **kwargs)
    if on_done:
        w.signals.done.connect(on_done)
    QThreadPool.globalInstance().start(w)
    return w
