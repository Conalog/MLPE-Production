from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class TestDetail:
    case: str
    parameter: dict[str, Any]  # Changed from log: str
    code: int


@dataclass
class Mlpe:
    device_id: Optional[str] = None      # 8-char hex (e.g., 0xAABBCCDD)
    ficr: Optional[dict[str, Any]] = None
    info: Optional[dict[str, Any]] = None  # REQ_GET_INFO result

    def reset(self):
        self.device_id = None
        self.ficr = None
        self.info = None


@dataclass
class AggregatedResult:
    test: str  # e.g., "self", "stage1"
    code: int
    device_id: Optional[str] = None      # Lower 4-byte ID (hex string, e.g., 0xAABBCCDD)
    upper_id: Optional[int] = None       # Upper 2-byte ID (integer)
    details: list[TestDetail] = field(default_factory=list)
    boot_data: Optional[dict[str, Any]] = None  # Additional context (e.g., boot info)

    def to_dict(self) -> dict[str, Any]:
        # Generate message: "Success" or "Failed(first_failed_test_name)"
        if self.code == 0:
            message = "Success"
        else:
            failed = next((d for d in self.details if d.code != 0), None)
            message = f"Failed({failed.case})" if failed else "Failed"
        
        # Combined 6-byte device ID (12 chars hex)
        # If device_id starts with 0x, strip it.
        # Fallback to local device_id if upper_id is missing (Stage 1 usually has 6-byte FICR addr)
        lower_id_str = self.device_id or ""
        if lower_id_str.startswith("0x"):
            lower_id_str = lower_id_str[2:]
        
        if self.upper_id is not None:
            try:
                if isinstance(self.upper_id, str):
                    u_int = int(self.upper_id, 16) if self.upper_id.startswith("0x") else int(self.upper_id)
                else:
                    u_int = int(self.upper_id)
                combined_id = f"{u_int:04X}{lower_id_str.zfill(8)}".upper()
            except (ValueError, TypeError):
                # If conversion fails, fallback to string concat if upper_id looks like hex
                combined_id = f"{self.upper_id}{lower_id_str.zfill(8)}".upper().replace("0X", "")
        else:
            combined_id = lower_id_str.upper().zfill(12)

        d = {
            "deviceid": combined_id,
            "message": message,
            "test": self.test,
            "code": self.code,
            "details": [
                {"case": b.case, "code": b.code, "parameter": b.parameter}
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


