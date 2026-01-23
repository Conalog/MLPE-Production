from __future__ import annotations

import time
import logging
import json
import signal
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
    stage: int = 1
    timezone: str = "Asia/Seoul"
    adc_scales: list[float] = field(default_factory=lambda: [6.0, 2.0, 1.0, 1.0])
    server_config: dict[str, Any] = field(default_factory=dict)

    def update_from_jig_config(self, jig_cfg: Any) -> None:
        """Update mutable fields from a JigConfig object."""
        # dataclass(frozen=True)이므로 __dict__를 통해 강제 업데이트하거나 
        # 새 객체를 만들어야 함. 여기서는 편의상 필드별로 업데이트 (frozen=True 주의)
        object.__setattr__(self, 'vendor', jig_cfg.vendor)
        object.__setattr__(self, 'product', jig_cfg.product)
        object.__setattr__(self, 'timezone', jig_cfg.timezone)
        object.__setattr__(self, 'adc_scales', jig_cfg.adc_scales)

    @classmethod
    def from_json(cls, jig_config_path: str, io_config_path: str, server_config_path: str, logs_base_dir: str) -> Stage1Config:
        from common.config_utils import load_json, parse_jig_config, parse_stage1_pins, get_hostname_jig_id

        # Hostname 기반 ID 생성 (Source of Truth)
        jig_id = get_hostname_jig_id()
        
        jig_cfg_raw = load_json(jig_config_path)
        # 파일의 ID와 hostname ID가 다르면 hostname ID로 강제 고정 및 파일 업데이트
        if jig_cfg_raw.get("jig_id") != jig_id:
            from common.config_utils import atomic_save_json
            jig_cfg_raw["jig_id"] = jig_id
            try:
                atomic_save_json(jig_config_path, jig_cfg_raw)
            except Exception:
                pass
            
        jig_cfg = parse_jig_config(jig_cfg_raw)
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

    # --- Signal Handling for Graceful Shutdown ---
    stop_requested = False
    def sigterm_handler(signum, frame):
        nonlocal stop_requested
        logger.info("SIGTERM received. Will exit gracefully after current sequence.")
        stop_requested = True
    
    signal.signal(signal.SIGTERM, sigterm_handler)

    # 2) db 서버 초기화
    from common.db_server import create_db_server
    db_server = create_db_server(cfg.server_config, jig_id=cfg.jig_id)

    bridge_host = cfg.server_config.get("bridge_host", "localhost")
    bridge_port = cfg.server_config.get("bridge_port", 1883)
    g.bridge = SolarBridgeClient(host=bridge_host, port=bridge_port, timeout=3.0)
    g.bridge.start()
    
    # ADC 공식 데이터 로드
    try:
        with open("configs/adc_values.json", "r") as f:
            adc_config = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load adc_values.json: {e}")
        adc_config = {}

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
    while not stop_requested:
        # 3-1) 인터넷 연결 확인
        io.set_loading(led_color="blue")
        net_ok = check_internet(timeout_s=3.0)
        log_event(logger, event="boot.internet_check", stage="stage1", data={"ok": net_ok})

        if not net_ok:
            io.show_code(E_INTERNET_NOT_FOUND.code)
            logger.error(f"Internet connection failed (Code: {E_INTERNET_NOT_FOUND.code}). Check network and press button.")
            # 버튼이 눌릴 때까지 혹은 종료 요청이 올 때까지 대기
            while not stop_requested:
                if io.wait_for_button(timeout=1.0):
                    break
            log_event(logger, event="stage1.boot.retry_requested", stage="stage1", data={"reason": "internet_fail"})
            continue

        # 3-2) DB 서버 연결 확인
        if db_server:
            db_ok = db_server.health_check(logger=logger)
            log_event(logger, event="boot.db_check", stage="stage1", data={"ok": db_ok})
            if not db_ok:
                io.show_code(E_DB_CONNECTION_FAILED.code)
                logger.error(f"DB Server connection failed (Code: {E_DB_CONNECTION_FAILED.code}). Check server status and press button.")
                # 버튼이 눌릴 때까지 혹은 종료 요청이 올 때까지 대기
                while not stop_requested:
                    if io.wait_for_button(timeout=1.0):
                        break
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
    while not stop_requested:
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

        # 셀프 테스트 종료 직후 종료 요청 확인
        if stop_requested:
            break

        if results.code == 0:
            # 성공 시 대기 모드 진입 및 루프 탈출
            io.show_code(0)
            log_event(logger, event="stage1.ready", stage="stage1")
            break
        else:
            # self-test 실패 시 에러 코드 표시
            io.show_code(results.code)
            logger.error(f"Self-test failed (Code: {results.code}). Press the button to retry.")

            # 버튼이 눌릴 때까지 혹은 종료 요청이 올 때까지 대기
            while not stop_requested:
                if io.wait_for_button(timeout=1.0):
                    break
            log_event(logger, event="stage1.boot.retry_requested", stage="stage1", data={"reason": "self_test_fail"})
            continue

    # B) Self-test 성공 시 버튼 대기 루프
    try:
        waiting_message_shown = False
        while not stop_requested:
            if not waiting_message_shown:
                logger.info(">>> 대기 중: 테스트 버튼을 누르면 시작합니다...")
                waiting_message_shown = True

            if not io.wait_for_button(timeout=1.0):
                continue
                
            waiting_message_shown = False # 버튼 클릭 시 다음 대기를 위해 초기화
            io.set_loading(led_color="green")

            # 버튼이 눌렸을 때의 시퀀스
            logger.info(">>> 버튼 눌림 감지: 생산 시퀀스를 시작합니다.")
            
            # --- Local Config Refresh ---
            # 수퍼바이저가 배경에서 jig.json을 동기화하므로, 
            # 버튼 눌림 시점에 파일에서 최신 정보를 읽어 메모리에 반영합니다.
            try:
                from common.config_utils import load_json, parse_jig_config
                latest_data = load_json(cfg.jig_config_path)
                new_jig_cfg = parse_jig_config(latest_data)
                cfg.update_from_jig_config(new_jig_cfg)
                io.adc_scales = cfg.adc_scales
                logger.debug(f"Local config refreshed: {cfg.vendor}/{cfg.product}")
            except Exception as e:
                logger.error(f"Failed to refresh local config: {e}")

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
                stage_name="stage1",
                adc_config=adc_config
            )

            # 서버 로그 전송 (성공/실패 상관없이 시퀀스 종료 시 한 번만)
            if db_server:
                db_server.push_log(results.to_dict(), logger=logger)

            if results.code == 0:
                logger.info(">>> 시퀀스 완료. 다시 대기 상태로 돌아갑니다.")
                io.show_code(0)
            else:
                logger.error(f">>> 시퀀스 실패 (Code: {results.code}). 사용자의 버튼 확인을 대기합니다.")
                io.show_code(results.code)
                io.wait_for_button()
                continue

    except KeyboardInterrupt:
        logger.info("프로그램을 종료합니다.")
    finally:
        io.stop()
        if g.bridge:
            g.bridge.stop()

    return 0
