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

    @abc.abstractmethod
    def get_jig_config(self, jig_id: str, logger: logging.Logger | None = None) -> dict[str, Any] | None:
        """jig_id에 해당하는 설정을 서버에서 가져옵니다."""
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

        # Extract new fields from data and build the 4-column payload
        # data.pop() removes the field from data so remaining data becomes 'log'
        payload = {
            "jig": self.factory_id,
            "deviceid": data.pop("deviceid", ""),
            "message": data.pop("message", ""),
            "log": data  # Remaining: test, code, details, boot_data
        }

        try:
            response = requests.post(endpoint, json=payload, timeout=5.0)
            if response.status_code != 200 and response.status_code != 201:
                # 에러 상세 내용 확인
                error_info = response.json() if response.headers.get('Content-Type') == 'application/json' else response.text
                if logger:
                    log_event(logger, event="db.push.fail", level=logging.WARNING, 
                              data={"server": "test", "status": response.status_code, "error": error_info})
                
                # 사용자가 화면에서 바로 볼 수 있도록 콘솔에 상세 에러 출력
                print(f"\n[DB_PUSH_ERROR] Status: {response.status_code}")
                print(f"[DB_PUSH_ERROR] Detail: {json.dumps(error_info, indent=2, ensure_ascii=False)}\n")
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

    def get_jig_config(self, jig_id: str, logger: logging.Logger | None = None) -> dict[str, Any] | None:
        """factory_config 컬렉션에서 설정을 조회합니다."""
        try:
            # 사용자가 확인해준 필드명 'jig'를 사용하여 조회합니다.
            record = self.pb.collection('factory_config').get_first_list_item(f'jig = "{jig_id}"')
            
            if record:
                # 'config'라는 이름의 JSON 필드가 있는지 확인
                # 사용자 제보: "그 내부에 config데이터가 전부 다 있다고"
                c_field = getattr(record, "config", {})
                if isinstance(c_field, str): # 가끔 문자열로 올 경우 대비
                    try:
                        c_field = json.loads(c_field)
                    except:
                        c_field = {}

                def get_val(key, default):
                    # 1. config 필드 내부에서 먼저 찾음
                    if isinstance(c_field, dict) and key in c_field:
                        return c_field[key]
                    # 2. 없으면 레코드 속성(Top-level)에서 찾음
                    return getattr(record, key, default)

                data = {
                    "jig_id": getattr(record, "jig", jig_id),
                    "vendor": get_val("vendor", ""),
                    "product": get_val("product", ""),
                    "stage": int(get_val("stage", 1)),
                    "timezone": get_val("timezone", "Asia/Seoul"),
                    "adc_scales": get_val("adc_scales", [6.0, 2.0, 1.0, 1.0]),
                }
                return data
            return None
        except Exception as e:
            if logger:
                log_event(logger, event="db.get_jig_config.fail", level=logging.WARNING, data={"jig_id": jig_id, "error": str(e)})
            
            # 사용자가 화면에서 바로 볼 수 있도록 콘솔에 상세 에러 출력
            print(f"\n[DB_CONFIG_ERROR] Failed to fetch config for jig_id: {jig_id}")
            print(f"[DB_CONFIG_ERROR] Detail: {e}\n")
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

    def get_jig_config(self, jig_id: str, logger: logging.Logger | None = None) -> dict[str, Any] | None:
        return None

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
