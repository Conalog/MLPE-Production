from gpiozero import RGBLED
from colorzero import Color
import time

class RGBLEDController:
    def __init__(self, red_pin=23, green_pin=22, blue_pin=27):
        """
        :param red_pin: Red LED BCM Pin (23)
        :param green_pin: Green LED BCM Pin (22)
        :param blue_pin: Blue LED BCM Pin (27)
        """
        try:
            # gpiozero의 RGBLED는 기본적으로 (Red, Green, Blue) 순서로 인자를 받습니다.
            # 요청하신 BGR 연결 순서에 맞춰 핀을 매핑합니다.
            self.led = RGBLED(red=red_pin, green=green_pin, blue=blue_pin)
            
            # 미리 정의된 색상 딕셔너리 (R, G, B) -> 값 범위 0~1
            self._colors = {
                "red": (1, 0, 0),
                "green": (0, 1, 0),
                "blue": (0, 0, 1),
                "white": (1, 1, 1),
                "black": (0, 0, 0),
                "off": (0, 0, 0),
                "yellow": (1, 1, 0),
                "cyan": (0, 1, 1),
                "magenta": (1, 0, 1),
                "orange": (1, 0.5, 0)
            }
        except Exception as e:
            raise

    def set_color(self, color_name: str):
        """
        색상 이름을 입력받아 LED 색상을 변경합니다.
        :param color_name: 'red', 'blue', 'white' 등 (대소문자 구분 없음)
        """
        name = color_name.lower()
        if name in self._colors:
            self.led.color = self._colors[name]
        else:
            try:
                self.led.color = Color(name).rgb
            except Exception:
                pass

    def cleanup(self):
        """리소스 해제"""
        if hasattr(self, 'led'):
            self.led.close()

# --- 테스트 실행부 ---
if __name__ == "__main__":
    led_ctrl = RGBLEDController()

    try:
        test_colors = ["red", "green", "blue", "white", "yellow", "black"]
        
        for c in test_colors:
            led_ctrl.set_color(c)
            time.sleep(1)
            
    except KeyboardInterrupt:
        pass
    finally:
        led_ctrl.set_color("black") # 끄기
        led_ctrl.cleanup()
