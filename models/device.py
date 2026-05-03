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
        name = self.model if self.model else self.serial
        if self.transport == Transport.TCPIP:
            return f"{name} (WiFi)"
        return name

    @property
    def is_connectable(self) -> bool:
        return self.state == DeviceState.DEVICE
