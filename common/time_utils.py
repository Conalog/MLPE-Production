from __future__ import annotations

import subprocess
import logging
import time
import requests
from common.logging_utils import log_event

def detect_timezone_by_ip(logger: logging.Logger | None = None) -> dict[str, Any] | None:
    """
    IP 기반 지오로케이션 API(ip-api.com)를 사용하여 현재 타임존 정보를 감지합니다.
    """
    try:
        response = requests.get("http://ip-api.com/json/", timeout=5.0)
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") == "success":
            if logger:
                log_event(logger, event="time.timezone.detected", data={"timezone": data.get("timezone"), "country": data.get("country"), "city": data.get("city")})
            return data
        else:
            if logger:
                log_event(logger, event="time.timezone.detect_fail", level=logging.WARNING, data={"reason": data.get("message")})
    except Exception as e:
        if logger:
            log_event(logger, event="time.timezone.detect_error", level=logging.WARNING, data={"error": str(e)})
    return None

def get_timezone_details(configured_tz: str, logger: logging.Logger | None = None) -> dict[str, Any]:
    """
    구성된 타임존, 시스템 타임존, 위치 정보(auto 인 경우) 및 KST 시간을 포함한 상세 정보를 반환합니다.
    """
    import datetime
    import pytz
    import subprocess

    details = {
        "configured_timezone": configured_tz,
        "system_timezone": "unknown",
        "location": None,
        "kst_time": datetime.datetime.now(pytz.timezone("Asia/Seoul")).isoformat(),
        "local_time": datetime.datetime.now().astimezone().isoformat()
    }

    try:
        details["system_timezone"] = subprocess.check_output(["timedatectl", "show", "--property=Timezone", "--value"], text=True).strip()
    except Exception:
        pass

    if configured_tz.lower() == "auto":
        loc_data = detect_timezone_by_ip(logger=logger)
        if loc_data:
            details["location"] = {
                "country": loc_data.get("country"),
                "city": loc_data.get("city"),
                "detected_timezone": loc_data.get("timezone")
            }
    
    return details

def set_system_timezone(timezone: str, logger: logging.Logger | None = None) -> bool:
    """
    timedatectl을 사용하여 시스템 타임존을 설정합니다.
    timezone이 'auto'인 경우 자동으로 감지하여 설정합니다.
    """
    target_tz = timezone
    if target_tz.lower() == "auto":
        detected_data = detect_timezone_by_ip(logger=logger)
        if detected_data and detected_data.get("timezone"):
            target_tz = detected_data["timezone"]
        else:
            # 감지 실패 시 기본값 유지 (혹은 에러 리턴)
            if logger:
                logger.warning("타임존 자동 감지 실패. 기존 설정을 유지합니다.")
            return False

    try:
        # 현재 타임존 확인
        current = subprocess.check_output(["timedatectl", "show", "--property=Timezone", "--value"], text=True).strip()
        if current == target_tz:
            if logger:
                log_event(logger, event="time.timezone.already_set", data={"timezone": target_tz})
            return True

        # 타임존 설정
        subprocess.run(["sudo", "timedatectl", "set-timezone", target_tz], check=True)
        # 현재 프로세스에 즉시 반영
        time.tzset()
        
        if logger:
            log_event(logger, event="time.timezone.updated", data={"from": current, "to": target_tz})
        return True
    except Exception as e:
        if logger:
            log_event(logger, event="time.timezone.error", level=logging.ERROR, data={"error": str(e), "target": target_tz})
        return False
