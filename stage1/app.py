from __future__ import annotations

import time
import logging
import json
from dataclasses import dataclass, field
from typing import Any

from common.logging_utils import build_logger, ensure_log_dir, log_event
from stage1.io_thread import IOThread
from stage1.self_test import run_self_test
from stage1 import globals as g
from common.solar_bridge import SolarBridgeClient


@dataclass(frozen=True)
class Stage1Config:
    jig_config_path: str
    io_config_path: str
    server_config_path: str

    # TM1637 (BCM)
    tm1637_dio: int
    tm1637_clk: int

    # Relay
    relay_pin: int
    relay_active_high: bool

    # LED / Button
    led_r: int
    led_g: int
    led_b: int
    button_pin: int

    # Logging
    logs_base_dir: str
    jig_id: str
    vendor: str
    product: str
    timezone: str = "Asia/Seoul"
    adc_scales: list[float] = field(default_factory=lambda: [6.0, 2.0, 1.0, 1.0])
    server_config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, jig_config_path: str, io_config_path: str, server_config_path: str, logs_base_dir: str) -> Stage1Config:
        from common.config_utils import load_json, parse_jig_config, parse_stage1_pins

        jig_cfg = parse_jig_config(load_json(jig_config_path))
        io_pins = parse_stage1_pins(load_json(io_config_path))
        server_cfg = load_json(server_config_path)

        return cls(
            jig_config_path=jig_config_path,
            io_config_path=io_config_path,
                server_config_path=server_config_path,
            tm1637_dio=io_pins.tm1637_dio,
            tm1637_clk=io_pins.tm1637_clk,
            relay_pin=io_pins.relay_pin,
            relay_active_high=io_pins.relay_active_high,
            led_r=io_pins.led_r,
            led_g=io_pins.led_g,
            led_b=io_pins.led_b,
            button_pin=io_pins.button_pin,
            logs_base_dir=logs_base_dir,
            jig_id=jig_cfg.jig_id,
            vendor=jig_cfg.vendor,
            product=jig_cfg.product,
            timezone=jig_cfg.timezone,
            adc_scales=jig_cfg.adc_scales,
            server_config=server_cfg,
        )

def run_stage1(cfg: Stage1Config) -> int:
    from stage1.self_test import check_internet
    from common.error_codes import E_INTERNET_NOT_FOUND, E_DB_CONNECTION_FAILED

    # 1) Logger 생성
    log_dir = ensure_log_dir(cfg.logs_base_dir, "stage1")
    logger = build_logger(name="stage1", log_dir=log_dir, console=True, level=logging.INFO)

    # 2) db 서버 초기화
    from common.db_server import create_db_server
    db_server = create_db_server(cfg.server_config, jig_id=cfg.jig_id)

    # 3) Solar Bridge 클라이언트 전역 초기화
    bridge_host = cfg.server_config.get("bridge_host", "localhost")
    bridge_port = cfg.server_config.get("bridge_port", 1883)
    g.bridge = SolarBridgeClient(host=bridge_host, port=bridge_port, timeout=3.0)
    
    # 3) main에서 세븐세그/LED/Button 제어 스레드 생성
    io = IOThread(
        logger=logger,
        tm1637_dio=cfg.tm1637_dio,
        tm1637_clk=cfg.tm1637_clk,
        led_pins=(cfg.led_r, cfg.led_g, cfg.led_b),
        button_pin=cfg.button_pin,
        adc_scales=cfg.adc_scales,
    )
    io.start()
    io.wait_until_ready(timeout=2.0)

    # --- Phase 1: Environment Readiness (Internet & DB) ---
    while True:
        # 3-1) 인터넷 연결 확인
        io.set_loading(led_color="blue")
        net_ok = check_internet(timeout_s=3.0)
        log_event(logger, event="boot.internet_check", stage="stage1", data={"ok": net_ok})

        if not net_ok:
            io.show_code(E_INTERNET_NOT_FOUND.code)
            logger.error(f"Internet connection failed (Code: {E_INTERNET_NOT_FOUND.code}). Check network and press button.")
            io.wait_for_button()
            log_event(logger, event="stage1.boot.retry_requested", stage="stage1", data={"reason": "internet_fail"})
            continue

        # 3-2) DB 서버 연결 확인
        if db_server:
            db_ok = db_server.health_check(logger=logger)
            log_event(logger, event="boot.db_check", stage="stage1", data={"ok": db_ok})
            if not db_ok:
                io.show_code(E_DB_CONNECTION_FAILED.code)
                logger.error(f"DB Server connection failed (Code: {E_DB_CONNECTION_FAILED.code}). Check server status and press button.")
                io.wait_for_button()
                log_event(logger, event="stage1.boot.retry_requested", stage="stage1", data={"reason": "db_fail"})
                continue
        
        # 인터넷과 DB가 모두 준비되면 Init 루프 종료
        break

    # --- One-time Boot Setup (Only once when environment is ready) ---
    # 4) 타임존 설정
    from common.time_utils import set_system_timezone, get_timezone_details
    set_system_timezone(cfg.timezone, logger=None)
    set_system_timezone(cfg.timezone, logger=logger)

    tz_details = get_timezone_details(cfg.timezone, logger=logger)

    # 5) 여기서 boot 로그용 데이터를 생성 (전송은 self-test와 통합)
    boot_data = {
        "event": "stage1.boot",
        "jig_id": cfg.jig_id, 
        "vendor": cfg.vendor,
        "product": cfg.product,
        "adc_scales": cfg.adc_scales,
        "timezone": cfg.timezone,
        "system_timezone": tz_details.get("system_timezone"),
        "detected_timezone": tz_details.get("system_timezone"), # detected_timezone fallback
        "kst_time": tz_details.get("kst_time"),
        "local_time": tz_details.get("local_time"),
    }
    if tz_details.get("location"):
        loc = tz_details["location"]
        boot_data.update({
            "location_country": loc.get("country"),
            "location_city": loc.get("city"),
            "detected_timezone": loc.get("detected_timezone"),
        })
    log_event(logger, event="stage1.boot", stage="stage1", data=boot_data)
    
    # --- Phase 2: Hardware Self-Test ---
    while True:
        io.set_loading(led_color="yellow")
        results = run_self_test(
            logger=logger,
            io=io,
            jig_id=cfg.jig_id,
            config_path=cfg.jig_config_path,
        )
        
        # 부팅 정보를 self-test 로그의 boot_data 키에 추가
        results.boot_data = boot_data

        if db_server:
            db_server.push_log(results.to_dict(), logger=logger)

        if results.code == 0:
            # 성공 시 대기 모드 진입 및 루프 탈출
            io.show_code(0)
            log_event(logger, event="stage1.ready", stage="stage1")
            break
        else:
            # self-test 실패 시 에러 코드 표시
            io.show_code(results.code)
            logger.error(f"Self-test failed (Code: {results.code}). Press the button to retry.")

            # 버튼 대기 후 재시작 (셀프테스트 루프 처음으로 이동)
            io.wait_for_button()
            log_event(logger, event="stage1.boot.retry_requested", stage="stage1", data={"reason": "self_test_fail"})
            continue

    # B) Self-test 성공 시 버튼 대기 루프
    try:
        while True:
            print("\n>>> 대기 중: 테스트 버튼을 누르면 시작합니다...")
            io.wait_for_button()
            io.set_loading(led_color="green")

            # 버튼이 눌렸을 때의 시퀀스
            print(">>> 버튼 눌림 감지: 생산 시퀀스를 시작합니다.")
            log_event(logger, event="stage1.sequence.start", stage="stage1")
            
            # 전역 MLPE 상태 초기화 (이전 테스트 결과 보관 방지)
            g.target_device.reset()

            from stage1.steps import run_stage_test

            # 1단계 양산 시퀀스 실행
            results = run_stage_test(
                logger=logger,
                io=io,
                db_server=db_server,
                vendor=cfg.vendor,
                product=cfg.product,
                stage_name="stage1"
            )

            # 서버 로그 전송 (성공/실패 상관없이 시퀀스 종료 시 한 번만)
            if db_server:
                db_server.push_log(results.to_dict(), logger=logger)

            if results.code == 0:
                print(">>> 시퀀스 완료. 다시 대기 상태로 돌아갑니다.")
                io.show_code(0)
            else:
                print(f">>> 시퀀스 실패 (Code: {results.code}). 사용자의 버튼 확인을 대기합니다.")
                io.show_code(results.code)
                io.wait_for_button()
                continue

    except KeyboardInterrupt:
        print("\n프로그램을 종료합니다.")
    finally:
        io.stop()

    return 0
