from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional


def _json_default(o: Any) -> Any:
    if is_dataclass(o):
        return asdict(o)
    return str(o)


def ensure_log_dir(base_dir: str | Path, stage: str) -> Path:
    """
    Create per-stage/per-day directory:
      logs/<stage>/<YYYYMMDD>/
    """
    base = Path(base_dir)
    day = datetime.now().strftime("%Y%m%d")
    target = base / stage / day
    target.mkdir(parents=True, exist_ok=True)
    return target


class ConsoleFormatter(logging.Formatter):
    """
    JSON으로 들어오는 로그 메시지에서 'event' 필드만 추출하여 출력하거나,
    일반 텍스트 메시지를 그대로 출력하는 콘솔용 포맷터.
    포맷: <stage> <PrintLevel> <Time(Local)> <Event>
    """
    def format(self, record: logging.LogRecord) -> str:
        # 시간 정보 생성 (기존 datefmt 및 asctime 사용)
        record.asctime = self.formatTime(record, self.datefmt)
        
        # 메시지가 JSON 형태인 경우 event만 추출 시도
        try:
            data = json.loads(record.msg)
            if isinstance(data, dict) and "event" in data:
                event_str = data["event"]
                # 괄호 없이 요청하신 순서대로 구성
                return f"{record.name} {record.levelname} {record.asctime}.{int(record.msecs):03d} {event_str}"
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
        
        # 일반 메시지인 경우
        return f"{record.name} {record.levelname} {record.asctime}.{int(record.msecs):03d} {record.msg}"


def build_logger(
    *,
    name: str,
    log_dir: str | Path,
    console: bool = True,
    level: int = logging.INFO,
    max_bytes: int = 2_000_000,
    backup_count: int = 5,
) -> logging.Logger:
    """
    Recommended for Raspberry Pi: rotate files, avoid huge logs.
    Creates:
      - <log_dir>/<name>.log (plain text)
      - <log_dir>/<name>.jsonl (one JSON per line)
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    # Avoid duplicate handlers if called multiple times
    if getattr(logger, "_configured", False):
        return logger

    Path(log_dir).mkdir(parents=True, exist_ok=True)
    txt_path = Path(log_dir) / f"{name}.log"
    jsonl_path = Path(log_dir) / f"{name}.jsonl"

    fmt = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        txt_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    jsonl_handler = RotatingFileHandler(
        jsonl_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    jsonl_handler.setLevel(level)
    jsonl_handler.setFormatter(logging.Formatter(fmt="%(message)s"))
    logger.addHandler(jsonl_handler)

    if console:
        ch = logging.StreamHandler()
        ch.setLevel(level)
        # 커스텀 포맷터 적용: <stage> <PrintLevel> <Time(Local)> <Event>
        ch.setFormatter(ConsoleFormatter(datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(ch)

    logger._configured = True  # type: ignore[attr-defined]
    return logger


def log_event(
    logger: logging.Logger,
    *,
    event: str,
    level: int = logging.INFO,
    stage: Optional[str] = None,
    data: Optional[dict[str, Any]] = None,
) -> None:
    now = datetime.now()
    # KST (UTC+9)
    kst = datetime.now(timezone(timedelta(hours=9)))
    
    payload: dict[str, Any] = {
        "ts": now.isoformat(timespec="milliseconds"),
        "ts_kst": kst.isoformat(timespec="milliseconds"),
        "event": event,
    }
    if stage:
        payload["stage"] = stage
    if data:
        payload["data"] = data

    msg = json.dumps(payload, ensure_ascii=False, default=_json_default)
    logger.log(level, msg)


def env_or_default(key: str, default: str) -> str:
    v = os.environ.get(key)
    return v if v not in (None, "") else default

