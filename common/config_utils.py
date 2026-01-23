from __future__ import annotations

import json
import socket
import tempfile
import shutil
import threading
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    pass


def load_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise ConfigError(f"config not found: {p}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ConfigError(f"invalid json: {p}: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"config root must be object: {p}")
    return data
 
 
def atomic_save_json(path: str | Path, data: dict[str, Any]) -> None:
    """Save JSON data to a file atomically using a temporary file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    
    # Create a temporary file in the same directory to ensure it's on the same filesystem
    with tempfile.NamedTemporaryFile('w', dir=p.parent, delete=False, encoding='utf-8') as tf:
        json.dump(data, tf, indent=2, ensure_ascii=False)
        tempname = tf.name
        
    try:
        shutil.move(tempname, p)
    except Exception:
        if Path(tempname).exists():
            Path(tempname).unlink()
        raise


def get_hostname_jig_id() -> str:
    """Returns the full system hostname."""
    return socket.gethostname()


class ConfigSyncThread(threading.Thread):
    """Background thread to sync configuration from DB and detect stage changes."""
    def __init__(self, 
                 db_server: Any, 
                 jig_id: str, 
                 config_path: str, 
                 interval: float = 3.0,
                 on_stage_changed: Any | None = None,
                 logger: logging.Logger | None = None):
        super().__init__(daemon=True)
        self.db_server = db_server
        self.jig_id = jig_id
        self.config_path = config_path
        self.interval = interval
        self.on_stage_changed = on_stage_changed
        self.logger = logger
        self._stop_event = threading.Event()
        
        # Initial stage to detect changes
        self.current_stage = self._load_current_stage()

    def _load_current_stage(self) -> int | None:
        try:
            data = load_json(self.config_path)
            return data.get("stage")
        except Exception:
            return None

    def stop(self):
        self._stop_event.set()

    def run(self):
        if self.logger:
            self.logger.info(f"[Sync] Started for Jig ID: {self.jig_id} (Interval: {self.interval}s)")

        while not self._stop_event.is_set():
            try:
                # Pass logger to see why it fails
                latest_data = self.db_server.get_jig_config(self.jig_id, logger=self.logger)
                
                if latest_data:
                    new_stage = latest_data.get("stage")
                    
                    # Atomic update of the local file
                    atomic_save_json(self.config_path, latest_data)
                    
                    # Check for stage change
                    if self.current_stage is not None and new_stage is not None:
                        if int(new_stage) != int(self.current_stage):
                            if self.logger:
                                self.logger.info(f"[Sync] Stage change detected: {self.current_stage} -> {new_stage}")
                            if self.on_stage_changed:
                                self.on_stage_changed(int(new_stage))
                            self.current_stage = int(new_stage)
                    elif self.current_stage is None and new_stage is not None:
                        self.current_stage = int(new_stage)
                else:
                    # Config found but empty or not found
                    if self.logger:
                        self.logger.debug(f"[Sync] No config response for ID: {self.jig_id}")
                
            except Exception as e:
                if self.logger:
                    self.logger.error(f"[Sync] ConfigSyncThread error: {e}")
            
            self._stop_event.wait(self.interval)


def _get(d: dict[str, Any], path: str) -> Any:
    cur: Any = d
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            raise ConfigError(f"missing config key: {path}")
        cur = cur[key]
    return cur


def _get_int(d: dict[str, Any], path: str) -> int:
    v = _get(d, path)
    if not isinstance(v, int):
        raise ConfigError(f"config key must be int: {path}")
    return v


def _get_bool(d: dict[str, Any], path: str) -> bool:
    v = _get(d, path)
    if not isinstance(v, bool):
        raise ConfigError(f"config key must be bool: {path}")
    return v


def _get_str(d: dict[str, Any], path: str) -> str:
    v = _get(d, path)
    if not isinstance(v, str) or v.strip() == "":
        raise ConfigError(f"config key must be non-empty string: {path}")
    return v


@dataclass(frozen=True)
class Stage1Pins:
    tm1637_dio: int
    tm1637_clk: int
    relay_pin: int
    relay_active_high: bool
    led_r: int
    led_g: int
    led_b: int
    button_pin: int


@dataclass(frozen=True)
class JigConfig:
    jig_id: str
    vendor: str
    product: str
    stage: int = 1
    timezone: str = "Asia/Seoul"
    adc_scales: list[float] = field(default_factory=lambda: [6.0, 2.0, 1.0, 1.0])


def parse_jig_config(data: dict[str, Any]) -> JigConfig:
    jig_id = _get_str(data, "jig_id")
    vendor = _get_str(data, "vendor")
    product = _get_str(data, "product")
    stage = data.get("stage", 1)  # Default to 1 if not present
    # timezone은 필수항목이 아닐 수 있으므로 기본값 처리 가능하도록 get 사용
    timezone = data.get("timezone", "Asia/Seoul")
    
    # adc_scales 처리
    scales = data.get("adc_scales")
    if scales is None:
        return JigConfig(jig_id=jig_id, vendor=vendor, product=product, stage=stage, timezone=timezone)
    
    if not isinstance(scales, list) or len(scales) != 4:
        raise ConfigError(f"adc_scales는 4개의 숫자를 포함하는 리스트여야 합니다 (현재: {scales})")
    
    try:
        scales = [float(s) for s in scales]
    except (ValueError, TypeError):
        raise ConfigError(f"adc_scales의 모든 요소는 숫자여야 합니다 (현재: {scales})")
        
    return JigConfig(jig_id=jig_id, vendor=vendor, product=product, stage=stage, timezone=timezone, adc_scales=scales)


def parse_stage1_pins(data: dict[str, Any]) -> Stage1Pins:
    """
    IO 핀 설정은 모든 jig(1/2/3 단계)가 공유하는 별도 configs/io.json에서 읽는다.
    Stage1용 핀맵은 다음과 같은 구조를 가정한다.

    {
      "tm1637": { "dio": 9, "clk": 10 },
      "relay": { "pin": 25, "active_high": false },
      "led":   { "r": 23, "g": 22, "b": 27 },
      "button": { "pin": 24 }
    }
    """
    return Stage1Pins(
        tm1637_dio=_get_int(data, "tm1637.dio"),
        tm1637_clk=_get_int(data, "tm1637.clk"),
        relay_pin=_get_int(data, "relay.pin"),
        relay_active_high=_get_bool(data, "relay.active_high"),
        led_r=_get_int(data, "led.r"),
        led_g=_get_int(data, "led.g"),
        led_b=_get_int(data, "led.b"),
        button_pin=_get_int(data, "button.pin"),
    )

