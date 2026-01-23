from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class TestDetail:
    case: str
    log: str
    code: int


@dataclass
class Mlpe:
    device_id: Optional[str] = None      # 8-char hex (e.g., 0xAABBCCDD)
    device_addr: Optional[str] = None    # 12-char hex (full FICR device addr)
    ficr: Optional[dict[str, Any]] = None
    info: Optional[dict[str, Any]] = None  # REQ_GET_INFO result
    baseline_vout: Optional[float] = None # Vout before relay

    def reset(self):
        self.device_id = None
        self.device_addr = None
        self.ficr = None
        self.info = None
        self.baseline_vout = None


@dataclass
class AggregatedResult:
    test: str  # e.g., "self", "stage3"
    code: int
    details: list[TestDetail] = field(default_factory=list)
    boot_data: Optional[dict[str, Any]] = None  # Additional context (e.g., boot info)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "test": self.test,
            "code": self.code,
            "details": [
                {"case": b.case, "log": b.log, "code": b.code}
                for b in self.details
            ]
        }
        if self.boot_data:
            d["boot_data"] = self.boot_data
        return d


@dataclass(frozen=True)
class SelfTestResult:
    ok: bool
    error_code: int
    details: str = ""


@dataclass(frozen=True)
class StepResult:
    ok: bool
    details: str = ""
    code: int = 0
    
    # Context/Data fields
    ficr: Optional[dict] = None
    bootloader_path: Optional[str] = None
    application_path: Optional[str] = None
    info: Optional[dict] = None
    stick_uid: Optional[str] = None
