from PySide6.QtCore import QThread, Signal

from core import adb_bridge
from models.device import Device


class DeviceManager(QThread):
    device_added = Signal(object)
    device_removed = Signal(object)
    device_state_changed = Signal(object)

    _POLL_MS = 2000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._known: dict[str, Device] = {}

    def run(self):
        self._running = True
        while self._running:
            self._poll()
            self.msleep(self._POLL_MS)

    def stop(self):
        self._running = False
        self.wait(3000)

    def _poll(self):
        try:
            current = {d.serial: d for d in adb_bridge.list_devices()}
        except Exception:
            return

        known_serials = set(self._known)
        current_serials = set(current)

        for serial in current_serials - known_serials:
            self._known[serial] = current[serial]
            self.device_added.emit(current[serial])

        for serial in known_serials - current_serials:
            removed = self._known.pop(serial)
            self.device_removed.emit(removed)

        for serial in known_serials & current_serials:
            if current[serial].state != self._known[serial].state:
                self._known[serial] = current[serial]
                self.device_state_changed.emit(current[serial])
