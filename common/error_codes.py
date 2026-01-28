from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorCode:
    code: int
    name: str
    description: str


OK = ErrorCode(0, "OK", "정상")

# Self-test (부팅 직후, V1/V2 버튼 ON 이전)
E_TM1637_NOT_FOUND = ErrorCode(1, "TM1637_NOT_FOUND", "세븐세그 연결/통신 실패")
E_RELAY_INIT_FAIL = ErrorCode(2, "RELAY_INIT_FAIL", "릴레이 초기화 실패")
E_GPIO_UNAVAILABLE = ErrorCode(3, "GPIO_UNAVAILABLE", "GPIO 라이브러리/권한 문제")
E_JIG_ID_MISSING = ErrorCode(4, "JIG_ID_MISSING", "configs 설정 파일에서 jig_id를 찾을 수 없음")
E_ADS1115_NOT_FOUND = ErrorCode(5, "ADS1115_NOT_FOUND", "ADS1115 연결/통신 실패")
E_INTERNET_NOT_FOUND = ErrorCode(6, "INTERNET_NOT_FOUND", "인터넷 연결 실패")
E_DB_CONNECTION_FAILED = ErrorCode(7, "DB_CONNECTION_FAILED", "DB 서버 연결 실패")
E_JLINK_NOT_FOUND = ErrorCode(8, "JLINK_NOT_FOUND", "J-Link 디버거를 찾을 수 없음")
E_STICK_NOT_FOUND = ErrorCode(9, "STICK_NOT_FOUND", "연결된 Stick(UID)을 찾을 수 없음")
E_PRINTER_NOT_FOUND = ErrorCode(10, "PRINTER_NOT_FOUND", "라벨 프린터를 찾을 수 없음")

# Production Sequence Steps (1단계 양산 시퀀스: 100-199)
E_VOLTAGE_12V_OUT_OF_RANGE = ErrorCode(101, "VOLTAGE_12V_OUT_OF_RANGE", "12V 전압 범위를 벗어남")
E_VOLTAGE_3V3_OUT_OF_RANGE = ErrorCode(102, "VOLTAGE_3V3_OUT_OF_RANGE", "3.3V 전압 범위를 벗어남")
E_DEVICE_RECOGNITION_FAIL = ErrorCode(103, "DEVICE_RECOGNITION_FAIL", "장비 인식 실패 (probe-rs)")
E_FIRMWARE_DOWNLOAD_FAIL = ErrorCode(104, "FIRMWARE_DOWNLOAD_FAIL", "펌웨어 다운로드 실패")
E_FIRMWARE_UPLOAD_FAIL = ErrorCode(105, "FIRMWARE_UPLOAD_FAIL", "펌웨어 업로드 실패")
E_DEVICE_COMMUNICATION_FAIL = ErrorCode(106, "DEVICE_COMMUNICATION_FAIL", "장비 통신 테스트 실패 (Get Info)")
E_ADC_VERIFICATION_FAIL = ErrorCode(107, "ADC_VERIFICATION_FAIL", "장비 전압(ADC) 검증 실패")
E_MESH_CONFIG_FAIL = ErrorCode(108, "MESH_CONFIG_FAIL", "메쉬 설정 변경 실패")

# Stage 2 specific (2단계 양산 시퀀스: 200-299)
E_NEIGHBOR_NOT_FOUND = ErrorCode(201, "NEIGHBOR_NOT_FOUND", "주변 장치 탐색 실패 (Neighbor Scanner)")
E_DUTY_RATIO_VERIFICATION_FAIL = ErrorCode(202, "DUTY_RATIO_VERIFICATION_FAIL", "Duty Ratio 가변 테스트 검증 실패")
E_INPUT_POWER_CHECK_NOT_IMPLEMENTED = ErrorCode(203, "INPUT_POWER_NI", "입력 전원 확인 미구현")
E_PRODUCT_TYPE_NOT_IMPLEMENTED = ErrorCode(204, "PRODUCT_TYPE_NI", "제품 타입 판별 미구현")

# Stage 3 specific (3단계 양산 시퀀스: 300-399)
E_FINAL_MESH_CONFIG_FAIL = ErrorCode(301, "FINAL_MESH_CONFIG_FAIL", "최종 메쉬 설정 검증 실패")
E_LABEL_PRINT_FAIL = ErrorCode(302, "LABEL_PRINT_FAIL", "라벨 출력 실패")

