from dataclasses import dataclass, field
from enum import Enum


class DeviceState(Enum):
    DEVICE = "device"
    OFFLINE = "offline"
    UNAUTHORIZED = "unauthorized"
    UNKNOWN = "unknown"


class Transport(Enum):
    USB = "usb"
    TCPIP = "tcpip"


@dataclass
class Device:
    serial: str
    state: DeviceState = DeviceState.UNKNOWN
    transport: Transport = Transport.USB
    model: str = ""
    ip: str = ""
    port: int = 5555

    @property
    def display_name(self) -> str:
        if self.model:
            name = self.model
        elif self.transport == Transport.TCPIP:
            # mDNS or IP-connected device with no model info — show IP or generic
            name = f"Phone ({self.ip})" if self.ip else "Phone"
        elif len(self.serial) > 22 or "_tcp" in self.serial:
            # Long/mDNS-style serial misclassified as USB — show a clean label
            name = "Phone"
        else:
            name = self.serial
        if self.transport == Transport.TCPIP:
            return f"{name} (WiFi)"
        return name

    @property
    def is_connectable(self) -> bool:
        return self.state == DeviceState.DEVICE
