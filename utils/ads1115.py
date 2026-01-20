import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import time

class ADS1115Reader:
    def __init__(self, i2c_address: int = 0x48, gain: int = 1, scales: list[float] | None = None):
        # I2C 초기화
        try:
            self.i2c = busio.I2C(board.SCL, board.SDA)
            # ADS1115 객체 생성 (이미 여기서 주소 체크가 이루어집니다)
            self.ads = ADS.ADS1115(self.i2c, address=i2c_address)
            self.ads.gain = gain
        except ValueError as e:
            print(f"I2C 주소 오류: {e}")
            raise
        except Exception as e:
            print(f"장치 연결 실패: {e}")
            raise

        # 채널 설정 (정수 인덱스 사용으로 버전 호환성 확보)
        self._channels = [
            AnalogIn(self.ads, 0),
            AnalogIn(self.ads, 1),
            AnalogIn(self.ads, 2),
            AnalogIn(self.ads, 3),
        ]

        # 전압 보정 계수 (V1: 50k/10k=6x, V2: 10k/10k=2x)
        self._scale = scales if scales is not None else [6.0, 2.0, 1.0, 1.0]

    def _read_input_voltage(self, ch: int) -> float:
        try:
            # .voltage 값을 직접 읽어 스케일링
            return self._channels[ch].voltage * self._scale[ch]
        except Exception as e:
            print(f"채널 {ch} 읽기 중 에러: {e}")
            return 0.0

    def read_adc_0(self) -> float: return self._read_input_voltage(0)
    def read_adc_1(self) -> float: return self._read_input_voltage(1)
    def read_adc_2(self) -> float: return self._read_input_voltage(2)
    def read_adc_3(self) -> float: return self._read_input_voltage(3)

    def is_connected(self) -> bool:
        """가장 확실한 연결 확인 방법: 더미 읽기 시도"""
        try:
            # 실제로 전압 하나를 읽어보아 에러가 없는지 확인
            _ = self._channels[0].voltage
            return True
        except:
            return False

if __name__ == "__main__":
    try:
        # 객체를 생성할 때 에러가 나지 않으면 장치가 있는 것입니다.
        adc = ADS1115Reader(i2c_address=0x48)
        
        # 실제 연결 테스트
        if adc.is_connected():
            print("ADS1115 연결 상태: 정상 ✅")
            print("-" * 30)
            while True:
                v0 = adc.read_adc_0()
                v1 = adc.read_adc_1()
                print(f"A0: {v0:6.2f}V | A1: {v1:6.2f}V")
                time.sleep(0.5)
        else:
            print("장치 응답 없음 ❌")

    except Exception as e:
        print(f"실행 에러: {e}")
