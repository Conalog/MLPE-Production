from __future__ import annotations
import abc
import json
import logging
import requests
from typing import Any
from pocketbase import PocketBase
from packaging.version import parse
from common.logging_utils import log_event

class DBServer(abc.ABC):
    @abc.abstractmethod
    def push_log(self, data: dict[str, Any], logger: logging.Logger | None = None) -> bool:
        """주어진 데이터를 서버에 업로드합니다."""
        pass

    @abc.abstractmethod
    def health_check(self, logger: logging.Logger | None = None) -> bool:
        """서버 연결 상태를 확인합니다."""
        pass

    @abc.abstractmethod
    def download_firmware(self, vendor: str, product: str, fw_type: str = "application", logger: logging.Logger | None = None) -> tuple[bytes, str] | None:
        """Vendor, Product, Type에 맞는 펌웨어를 다운로드하고 (바이너리, 버전) 튜플을 반환합니다."""
        pass

class TestDBServer(DBServer):
    """PocketBase 기반 테스트 서버 구현"""
    def __init__(self, url: str, collection: str, factory_id: str):
        self.url = url.rstrip('/')
        self.collection = collection
        self.factory_id = factory_id # RELATION_RECORD_ID 매칭용 (예: 지그 ID 또는 공장 ID)
        self.pb = PocketBase(self.url)

    def push_log(self, data: dict[str, Any], logger: logging.Logger | None = None) -> bool:
        endpoint = f"{self.url}/api/collections/{self.collection}/records"

        # PocketBase 스키마에 맞게 변환
        # factory: RELATION_RECORD_ID
        # jig: string (지그 ID)
        # log: JSON object
        payload = {
            "factory": self.factory_id,
            "jig": self.factory_id,
            "jig_id": self.factory_id, # 대비용 필드 추가
            "log": data
        }

        try:
            response = requests.post(endpoint, json=payload, timeout=5.0)
            if response.status_code != 200 and response.status_code != 201:
                # 에러 상세 내용 확인
                error_info = response.json() if response.headers.get('Content-Type') == 'application/json' else response.text
                if logger:
                    log_event(logger, event="db.push.fail", level=logging.WARNING, 
                              data={"server": "test", "status": response.status_code, "error": error_info})
                return False
                
            if logger:
                log_event(logger, event="db.push.ok", level=logging.DEBUG, data={"server": "test", "id": response.json().get("id")})
            return True
        except Exception as e:
            if logger:
                log_event(logger, event="db.push.exception", level=logging.WARNING, data={"server": "test", "error": str(e)})
            return False

    def health_check(self, logger: logging.Logger | None = None) -> bool:
        # PocketBase health check endpoint
        endpoint = f"{self.url}/api/health"
        try:
            response = requests.get(endpoint, timeout=3.0)
            response.raise_for_status()
            # PocketBase returns {"code": 200, "message": "Health check successful", "data": {...}}
            return response.status_code == 200
        except Exception as e:
            if logger:
                log_event(logger, event="db.health_check.fail", level=logging.WARNING, data={"server": "test", "error": str(e)})
            return False

    def download_firmware(self, vendor: str, product: str, fw_type: str = "application", logger: logging.Logger | None = None) -> tuple[bytes, str] | None:
        """Vendor, Product, Type에 맞는 펌웨어를 다운로드하고 (바이너리, 버전) 튜플을 반환합니다."""
        try:
            # bootloader인 경우 vendor, product, type을 모두 "bootloader"로 고정
            # 그 외의 경우는 모두 "application"으로 처리 (FirmwareType Enum 의존성 제거)
            if fw_type == "bootloader":
                vendor = "bootloader"
                product = "bootloader"
                query_fw_type = "bootloader"
            else:
                query_fw_type = "application"

            filter_str = f'vendor = "{vendor}" && product = "{product}" && type = "{query_fw_type}"'
            
            if logger:
                log_event(logger, event="db.download_firmware.start", level=logging.INFO, 
                          data={"vendor": vendor, "product": product, "type": query_fw_type})

            # factory_firmwares_2 컬렉션에서 필터링된 리스트 가져오기
            records = self.pb.collection('factory_firmwares_2').get_full_list(query_params={
                "filter": filter_str
            })

            if not records:
                if logger:
                    log_event(logger, event="db.download_firmware.not_found", level=logging.WARNING, 
                              data={"vendor": vendor, "product": product, "type": fw_type})
                return None

            # 최신 버전 찾기 (Semantic Versioning 비교)
            latest_record = max(
                records, 
                key=lambda r: parse(getattr(r, "version", "0.0.0"))
            )
            
            latest_version = getattr(latest_record, "version", "unknown")
            file_field_value = getattr(latest_record, "firmware", None)

            if not file_field_value:
                if logger:
                    log_event(logger, event="db.download_firmware.no_file", level=logging.WARNING, 
                              data={"vendor": vendor, "product": product, "version": latest_version})
                return None

            # 다운로드 URL 생성 및 실행
            file_url = self.pb.get_file_url(latest_record, file_field_value)
            response = requests.get(file_url, timeout=10.0)
            
            if response.status_code == 200:
                if logger:
                    log_event(logger, event="db.download_firmware.ok", level=logging.INFO, 
                              data={"vendor": vendor, "product": product, "version": latest_version, "size": len(response.content)})
                return response.content, latest_version
            else:
                if logger:
                    log_event(logger, event="db.download_firmware.fail", level=logging.WARNING, 
                              data={"status": response.status_code, "url": file_url})
                return None

        except Exception as e:
            if logger:
                log_event(logger, event="db.download_firmware.exception", level=logging.ERROR, 
                          data={"error": str(e)})
            return None

class RealDBServer(DBServer):
    """실제 운영 서버 구현 (현재는 자리표시자)"""
    def __init__(self, url: str, api_key: str):
        self.url = url
        self.api_key = api_key

    def push_log(self, data: dict[str, Any], logger: logging.Logger | None = None) -> bool:
        # 실제 운영 서버의 API 규격에 맞춰 구현 (추후 확정)
        if logger:
            log_event(logger, event="db.push.real_placeholder", level=logging.INFO, data={"status": "not_implemented"})
        return True

    def health_check(self, logger: logging.Logger | None = None) -> bool:
        return True

    def download_firmware(self, vendor: str, product: str, fw_type: str = "application", logger: logging.Logger | None = None) -> tuple[bytes, str] | None:
        if logger:
            log_event(logger, event="db.download_firmware.real_placeholder", level=logging.INFO, 
                      data={"vendor": vendor, "product": product, "type": fw_type})
        prefix = b"BOOT_" if fw_type == "bootloader" else b"APP_"
        return prefix + b"\x00\x01\x02\x03_REAL_FIRMWARE_PLACEHOLDER", "1.0.0-real"

def create_db_server(config: dict[str, Any], jig_id: str) -> DBServer | None:
    """설정에 따라 적절한 DBServer 객체를 생성합니다."""
    server_type = config.get("type", "none").lower()
    url = config.get("url")

    if server_type == "test":
        collection = config.get("collection", "factory_logs_2")
        return TestDBServer(url=url, collection=collection, factory_id=jig_id)
    elif server_type == "real":
        api_key = config.get("api_key", "")
        return RealDBServer(url=url, api_key=api_key)

    return None
