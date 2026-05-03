"""
Auto-discovers the ADB connect port on a known IP by scanning the port range
that Android Wireless Debugging uses (37000-50000), falling back to a full
scan if nothing is found there.
"""

import socket
import concurrent.futures
from typing import Optional


def _is_open(ip: str, port: int, timeout: float = 0.15) -> Optional[int]:
    try:
        s = socket.socket()
        s.settimeout(timeout)
        s.connect((ip, port))
        s.close()
        return port
    except Exception:
        return None


def find_adb_port(ip: str) -> Optional[int]:
    """
    Return the first open port in the ADB wireless range on `ip`, or None.
    Tries the known Android Wireless Debugging range (37000-50000) first.
    """
    ranges = [range(37000, 50001), range(50001, 65536), range(1024, 37000)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=400) as ex:
        for r in ranges:
            results = list(ex.map(lambda p: _is_open(ip, p), r))
            found = [p for p in results if p]
            if found:
                # Return the lowest open port in the ADB range
                return min(found)
    return None


def is_reachable(ip: str) -> bool:
    """Quick check — try connecting to port 80 or ICMP-style TCP probe."""
    return _is_open(ip, 43825, timeout=0.5) is not None or _is_open(ip, 5555, timeout=0.5) is not None
