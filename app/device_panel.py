from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from models.device import Device, DeviceState

_STATE_COLOR = {
    DeviceState.DEVICE: "#4caf50",
    DeviceState.OFFLINE: "#9e9e9e",
    DeviceState.UNAUTHORIZED: "#ff9800",
    DeviceState.UNKNOWN: "#9e9e9e",
}

_STATE_LABEL = {
    DeviceState.DEVICE: "Connected",
    DeviceState.OFFLINE: "Offline",
    DeviceState.UNAUTHORIZED: "Unauthorized",
    DeviceState.UNKNOWN: "Unknown",
}


class DevicePanel(QWidget):
    mirror_requested = Signal(object)   # Device
    mirror_stop_requested = Signal()
    pair_wifi_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._devices: dict[str, Device] = {}
        self._mirroring_serial: str | None = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QLabel("Devices")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(header)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()

        self._btn_mirror = QPushButton("Start Mirror")
        self._btn_mirror.setEnabled(False)
        self._btn_mirror.clicked.connect(self._on_mirror_clicked)
        btn_row.addWidget(self._btn_mirror)

        self._btn_wifi = QPushButton("Add via WiFi…")
        self._btn_wifi.clicked.connect(self.pair_wifi_requested)
        btn_row.addWidget(self._btn_wifi)

        layout.addLayout(btn_row)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(self._status_label)

    # ── public API ────────────────────────────────────────────────────────────

    def add_device(self, device: Device):
        self._devices[device.serial] = device
        self._refresh_list()

    def remove_device(self, device: Device):
        self._devices.pop(device.serial, None)
        if self._mirroring_serial == device.serial:
            self._mirroring_serial = None
        self._refresh_list()

    def update_device(self, device: Device):
        self._devices[device.serial] = device
        self._refresh_list()

    def set_mirroring(self, serial: str | None):
        self._mirroring_serial = serial
        self._refresh_list()
        if serial:
            self._btn_mirror.setText("Stop Mirror")
            self._btn_mirror.setEnabled(True)
            self._status_label.setText(f"Mirroring {self._devices.get(serial, Device(serial)).display_name}")
        else:
            self._btn_mirror.setText("Start Mirror")
            self._status_label.setText("")
            self._on_selection_changed()

    def show_error(self, message: str):
        self._status_label.setStyleSheet("color: #f44336; font-size: 12px;")
        self._status_label.setText(message)

    def show_info(self, message: str):
        self._status_label.setStyleSheet("color: #666; font-size: 12px;")
        self._status_label.setText(message)

    # ── slots ─────────────────────────────────────────────────────────────────

    def _on_selection_changed(self):
        if self._mirroring_serial:
            return
        device = self._selected_device()
        if device and device.is_connectable:
            self._btn_mirror.setEnabled(True)
        else:
            self._btn_mirror.setEnabled(False)

        if device and device.state == DeviceState.UNAUTHORIZED:
            self._status_label.setStyleSheet("color: #ff9800; font-size: 12px;")
            self._status_label.setText("Check your phone and tap Allow for USB debugging.")
        elif device and device.state == DeviceState.OFFLINE:
            self._status_label.setStyleSheet("color: #9e9e9e; font-size: 12px;")
            self._status_label.setText("Device is offline.")
        else:
            self._status_label.setStyleSheet("color: #666; font-size: 12px;")
            self._status_label.setText("")

    def _on_mirror_clicked(self):
        if self._mirroring_serial:
            self.mirror_stop_requested.emit()
        else:
            device = self._selected_device()
            if device and device.is_connectable:
                self.mirror_requested.emit(device)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _selected_device(self) -> Device | None:
        items = self._list.selectedItems()
        if not items:
            return None
        serial = items[0].data(Qt.UserRole)
        return self._devices.get(serial)

    def _refresh_list(self):
        selected_serial = None
        if self._list.selectedItems():
            selected_serial = self._list.selectedItems()[0].data(Qt.UserRole)

        self._list.clear()
        for device in self._devices.values():
            label = device.display_name
            if self._mirroring_serial == device.serial:
                label += " ▶"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, device.serial)
            color = _STATE_COLOR.get(device.state, "#9e9e9e")
            item.setForeground(QColor(color))
            item.setToolTip(f"State: {_STATE_LABEL.get(device.state, '?')}\nSerial: {device.serial}")
            self._list.addItem(item)
            if device.serial == selected_serial:
                item.setSelected(True)

        self._on_selection_changed()
