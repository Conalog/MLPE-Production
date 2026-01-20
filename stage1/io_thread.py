from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

from common.logging_utils import log_event


@dataclass
class IOState:
    mode: str = "idle"  # idle | loading | show_code
    code: int = 0
    led_color: str = "off"  # off/red/green/blue/yellow...


class IOThread:
    """
    경량 IO 스레드:
    - TM1637 로딩 애니메이션(숫자 카운터) 또는 에러코드 표시
    - RGB LED 상태 표시
    - 버튼 폴링(현재는 자리만)

    NOTE:
    - LED/버튼은 '연결 확인' 대상이 아니므로, 초기화 실패해도 프로그램을 막지 않음(best-effort).
    - TM1637도 best-effort로 유지(불량이면 표시 기능이 제한될 수 있음).
    """

    def __init__(self, *, logger, tm1637_dio: int, tm1637_clk: int, led_pins=(23, 22, 27), button_pin: int = 24, adc_scales: list[float] | None = None):
        self._logger = logger
        self._tm_dio = tm1637_dio
        self._tm_clk = tm1637_clk
        self._led_pins = led_pins
        self._button_pin = button_pin
        self._adc_scales = adc_scales

        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._hw_lock = threading.Lock()  # 하드웨어 장치 접근 보호용 락
        self._state = IOState()

        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="stage1-io", daemon=True)

        # Best-effort devices (created inside thread as well)
        self._disp = None
        self._led = None
        self._btn = None
        self._adc = None

    def start(self) -> None:
        self._thread.start()

    def wait_until_ready(self, timeout: float = 5.0) -> bool:
        """초기화 완료될 때까지 대기"""
        return self._ready.wait(timeout=timeout)

    def get_ads1115_status(self) -> tuple[bool, Optional[str]]:
        with self._hw_lock:
            if self._adc is None:
                try:
                    from utils.ads1115 import ADS1115Reader
                    self._adc = ADS1115Reader(i2c_address=0x48, scales=self._adc_scales)
                except Exception as e:
                    return False, str(e)
            
            try:
                ok = self._adc.is_connected()
                return ok, None if ok else "Communication failed"
            except Exception as e:
                return False, str(e)

    def read_voltages(self) -> tuple[float, float]:
        """ADC 0번(12V)과 1번(3.3V) 채널의 전압을 읽어 반환합니다."""
        with self._hw_lock:
            if self._adc is None:
                return 0.0, 0.0
            try:
                v12 = self._adc.read_adc_0()
                v33 = self._adc.read_adc_1()
                return v12, v33
            except Exception:
                return 0.0, 0.0

    def stop(self, timeout: float = 1.0) -> None:
        self._stop.set()
        self._thread.join(timeout=timeout)
        self._cleanup()

    def set_loading(self, *, led_color: str = "blue") -> None:
        with self._lock:
            self._state.mode = "loading"
            self._state.led_color = led_color

    def show_code(self, code: int, *, led_color: str | None = None) -> None:
        with self._lock:
            self._state.mode = "show_code"
            self._state.code = int(code)
            if led_color is not None:
                self._state.led_color = led_color
            else:
                self._state.led_color = "white" if code == 0 else "red"

    def idle(self) -> None:
        with self._lock:
            self._state.mode = "idle"
            self._state.led_color = "off"

    def wait_for_button(self) -> None:
        """버튼이 눌릴 때까지 블로킹 대기 (best-effort)"""
        if self._btn is not None:
            try:
                self._btn.wait_until_push()
            except Exception as e:
                log_event(self._logger, event="io_thread.button.wait_fail", stage="stage1", data={"error": str(e)})
                time.sleep(1.0)  # 에러 시 무한 루프 방지용 대기
        else:
            # 버튼이 없으면 진행할 수 없으므로 잠시 대기 후 리턴하거나 예외를 던질 수 있음
            # 여기서는 운영 편의상 잠시 대기
            time.sleep(1.0)

    def _init_devices_best_effort(self) -> None:
        # TM1637
        if self._disp is None:
            try:
                from utils.tm1637 import TM1637Display

                self._disp = TM1637Display(dio_pin=self._tm_dio, clk_pin=self._tm_clk)
                log_event(self._logger, event="io_thread.tm1637.init.ok", stage="stage1")
            except Exception as e:
                self._disp = None
                log_event(self._logger, event="io_thread.tm1637.init.fail", stage="stage1", data={"error": str(e)})

        # LED
        if self._led is None:
            try:
                from utils.rgb_led import RGBLEDController

                r, g, b = self._led_pins
                self._led = RGBLEDController(red_pin=r, green_pin=g, blue_pin=b)
                log_event(self._logger, event="io_thread.led.init.ok", stage="stage1", data={"pins": [r, g, b]})
            except Exception as e:
                self._led = None
                log_event(self._logger, event="io_thread.led.init.fail", stage="stage1", data={"error": str(e)})

        # Button
        if self._btn is None:
            try:
                from utils.button import Button

                self._btn = Button(pin=self._button_pin)
                log_event(self._logger, event="io_thread.button.init.ok", stage="stage1", data={"pin": self._button_pin})
            except Exception as e:
                self._btn = None
                log_event(self._logger, event="io_thread.button.init.fail", stage="stage1", data={"error": str(e)})
        
        self._ready.set()

    def _cleanup(self) -> None:
        with self._hw_lock:
            try:
                if self._disp is not None:
                    self._disp.cleanup()
            except Exception:
                pass
            try:
                if self._led is not None:
                    self._led.set_color("off")
                    self._led.cleanup()
            except Exception:
                pass
            try:
                if self._adc is not None:
                    self._adc = None
            except Exception:
                pass

    def _apply_led(self, color: str) -> None:
        with self._hw_lock:
            if self._led is None:
                return
            try:
                self._led.set_color(color)
            except Exception:
                pass

    def _display_number(self, value: int, *, leading_zero: bool = True) -> None:
        with self._hw_lock:
            if self._disp is None:
                return
            try:
                self._disp.display_number(int(value), leading_zero=leading_zero)
            except Exception:
                pass

    def _display_segments(self, segs: list[int]) -> None:
        with self._hw_lock:
            if self._disp is None:
                return
            try:
                self._disp.write_segments(segs)
            except Exception:
                pass

    def _run(self) -> None:
        with self._hw_lock:
            self._init_devices_best_effort()

        counter = 0
        last_led = None

        # 로딩 애니메이션 (테두리 닦기 패턴)
        # A(0x01), B(0x02), C(0x04), D(0x08), E(0x10), F(0x20)
        # 0x3F(All) -> 0x3E(A-off) -> 0x3C(B-off) -> 0x38(C-off) -> 0x30(D-off) -> 0x20(E-off) -> 0x00(F-off)
        LOADING_FRAMES = [0x3F, 0x3E, 0x3C, 0x38, 0x30, 0x20, 0x00]

        while not self._stop.is_set():
            with self._lock:
                st = IOState(mode=self._state.mode, code=self._state.code, led_color=self._state.led_color)

            if st.led_color != last_led:
                self._apply_led(st.led_color)
                last_led = st.led_color

            if st.mode == "loading":
                frame_idx = counter % len(LOADING_FRAMES)
                self._display_segments([LOADING_FRAMES[frame_idx]] * 4)
                counter += 1
                time.sleep(0.12)
            elif st.mode == "show_code":
                self._display_number(st.code, leading_zero=True)
                time.sleep(0.25)
            else:
                time.sleep(0.25)

            # 버튼 폴링 (현재는 자리만)
            if self._btn is not None:
                try:
                    _ = self._btn.is_pressed()
                except Exception:
                    pass

