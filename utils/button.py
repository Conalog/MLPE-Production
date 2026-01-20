from gpiozero import Button as GZButton
import time

class Button:
    def __init__(self, pin: int = 24, bounce_time: float = 0.05):
        """
        Active High 방식의 버튼 클래스 (Ubuntu 24.04 대응)
        """
        try:
            # pull_up을 None으로 두어 하드웨어의 현재 상태를 강제로 바꾸지 않고
            # 핀이 1(High)이 되었을 때를 '눌림'으로 인식하게 합니다.
            self.device = GZButton(pin, pull_up=None, active_state=True, bounce_time=bounce_time)
            self.pin = pin
        except Exception as e:
            print(f"버튼 초기화 실패 (GPIO {pin}): {e}")
            raise

    def wait_until_push(self):
        """버튼이 눌릴 때(High가 될 때)까지 대기"""
        print(f"버튼 대기 중 (현재 Low 상태 정상, BCM {self.pin})...")
        self.device.wait_for_press()
        # time.sleep(0.01)

    def is_pressed(self) -> bool:
        return self.device.is_pressed

if __name__ == '__main__':
    btn = Button(pin=24)
    try:
        print("--- 테스트 시작 ---")
        while True:
            btn.wait_until_push()
            print("버튼 감지됨! ✅")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n종료합니다.")
