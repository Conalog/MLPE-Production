from gpiozero import DigitalOutputDevice, DigitalInputDevice
import time

class TM1637Display:
    """
    TM1637 4-digit 7-segment driver using gpiozero.
    일반 유저(pi) 권한으로 실행 가능합니다.
    """

    _CMD_DATA_AUTO = 0x40
    _CMD_ADDR_BASE = 0xC0
    _CMD_DISPLAY_CTRL = 0x88

    _DIGIT_TO_SEG = {
        0: 0x3F, 1: 0x06, 2: 0x5B, 3: 0x4F, 4: 0x66,
        5: 0x6D, 6: 0x7D, 7: 0x07, 8: 0x7F, 9: 0x6F
    }
    _BLANK = 0x00

    def __init__(self, dio_pin: int = 9, clk_pin: int = 10, brightness: int = 7):
        # gpiozero의 DigitalOutputDevice를 사용하여 핀 초기화
        self._clk = DigitalOutputDevice(clk_pin, initial_value=True)
        # DIO는 입출력 전환이 잦으므로 초기엔 출력으로 설정
        self._dio = DigitalOutputDevice(dio_pin, initial_value=True)
        
        self.dio_pin_number = dio_pin # ACK 확인 시 재설정을 위함
        self.delay = 0.000005 # 5us
        self.brightness = max(0, min(7, brightness))
        
        self.clear()

    def _start(self):
        self._dio.on()
        self._clk.on()
        time.sleep(self.delay)
        self._dio.off()
        time.sleep(self.delay)
        self._clk.off()

    def _stop(self):
        self._clk.off()
        time.sleep(self.delay)
        self._dio.off()
        time.sleep(self.delay)
        self._clk.on()
        time.sleep(self.delay)
        self._dio.on()

    def _write_byte(self, data: int) -> bool:
        # 8 bits write
        for _ in range(8):
            self._clk.off()
            if data & 0x01:
                self._dio.on()
            else:
                self._dio.off()
            time.sleep(self.delay)
            self._clk.on()
            time.sleep(self.delay)
            data >>= 1

        # ACK bit check
        self._clk.off()
        self._dio.close() # 기존 출력 장치 닫기
        
        # 입력을 위해 일시적으로 input 객체 생성
        ack_input = DigitalInputDevice(self.dio_pin_number, pull_up=True)
        time.sleep(self.delay)
        self._clk.on()
        time.sleep(self.delay)
        ack = (ack_input.value == 0) # TM1637이 LOW를 주면 성공
        self._clk.off()
        
        ack_input.close() # 입력 장치 닫기
        # 다시 출력 장치로 복구
        self._dio = DigitalOutputDevice(self.dio_pin_number, initial_value=False)
        
        return ack

    def display_number(self, value: int, leading_zero: bool = False):
        if not (0 <= value <= 9999):
            return

        s = f"{value:04d}" if leading_zero else str(value).rjust(4)
        segs = [self._DIGIT_TO_SEG[int(c)] if c.isdigit() else self._BLANK for c in s]
        
        # Data Command
        self._start()
        self._write_byte(self._CMD_DATA_AUTO)
        self._stop()

        # Address Command + Data
        self._start()
        self._write_byte(self._CMD_ADDR_BASE)
        for i in range(4):
            self._write_byte(segs[i])
        self._stop()

        # Control Command
        self._start()
        self._write_byte(self._CMD_DISPLAY_CTRL | self.brightness)
        self._stop()

    def write_segments(self, segs: list[int]):
        """로우 세그먼트 데이터를 직접 출력 (A:0x01, B:0x02, ..., G:0x40)"""
        if len(segs) != 4:
            return
        self._display_raw(segs)

    def clear(self):
        self._display_raw([self._BLANK] * 4)

    def _display_raw(self, segs):
        self._start()
        self._write_byte(self._CMD_DATA_AUTO)
        self._stop()
        self._start()
        self._write_byte(self._CMD_ADDR_BASE)
        for s in segs: self._write_byte(s)
        self._stop()
        self._start()
        self._write_byte(self._CMD_DISPLAY_CTRL | self.brightness)
        self._stop()

    def cleanup(self):
        self._dio.close()
        self._clk.close()

if __name__ == '__main__':
    disp = TM1637Display()
    try:
        disp.display_number(1234)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        disp.clear()
        disp.cleanup()
