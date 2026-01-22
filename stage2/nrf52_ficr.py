from __future__ import annotations
from typing import List, Dict, Any


class NRF52FICR:
    """
    nRF52 Series Factory Information Configuration Registers (FICR) Parser.
    Base Address: 0x10000000
    """

    def __init__(self, words: List[int]):
        """
        :param words: List of 32-bit words starting from 0x10000000
        """
        self.words = words

    def get_device_id(self) -> str:
        """DEVICEID[0] at 0x060, DEVICEID[1] at 0x064"""
        if len(self.words) <= 25:
            return "UNKNOWN"
        # DEVICEID[0]: words[24], DEVICEID[1]: words[25]
        return f"{self.words[25]:08X}{self.words[24]:08X}"

    def get_device_addr(self) -> str:
        """DEVICEADDR[0] at 0x0A4, DEVICEADDR[1] at 0x0A8"""
        if len(self.words) <= 42:
            return "UNKNOWN"
        # DEVICEADDR[0]: words[41], DEVICEADDR[1]: words[42] (Upper 16 bits are reserved)
        addr_low = self.words[41]
        addr_high = self.words[42] & 0xFFFF
        return f"{addr_high:04X}{addr_low:08X}"

    def get_device_addr_type(self) -> str:
        """DEVICEADDRTYPE at 0x0AC"""
        if len(self.words) <= 43:
            return "unknown"
        # Bit 0: 0=Public, 1=Random
        return "public" if (self.words[43] & 0x01) == 0 else "random"

    def get_part(self) -> str:
        """INFO.PART at 0x100"""
        if len(self.words) <= 64:
            return "UNKNOWN"
        return f"N52{self.words[64]:08X}"

    def get_variant(self) -> str:
        """INFO.VARIANT at 0x104"""
        if len(self.words) <= 65:
            return "UNKNOWN"
        v = self.words[65]
        return "".join([chr((v >> (8 * i)) & 0xFF) for i in range(3, -1, -1)])

    def as_dict(self) -> Dict[str, Any]:
        """Returns all recognized info as a structured dictionary."""
        return {
            "device_id": self.get_device_id(),
            "device_addr": self.get_device_addr(),
            "device_addr_type": self.get_device_addr_type(),
            "part": self.get_part(),
            "variant": self.get_variant(),
        }
