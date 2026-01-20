from gpiozero import OutputDevice
import time

class RelayController:
    def __init__(self, pin: int = 25, active_high: bool = False):
        """
        :param pin: Relay Signal Pin BCM (25)
        :param active_high: 릴레이 특성에 따라 설정
               - True: High(1)일 때 켜짐 (일반적인 방식)
               - False: Low(0)일 때 켜짐 (대부분의 중국산/범용 릴레이 모듈 방식)
        """
        try:
            # OutputDevice를 사용하여 릴레이를 제어합니다.
            # 초기 상태(initial_value)는 꺼짐(False)으로 설정합니다.
            self.relay = OutputDevice(pin, active_high=active_high, initial_value=False)
            self.pin = pin
            print(f"릴레이 초기화 완료: GPIO {pin} (Active High={active_high})")
        except Exception as e:
            print(f"릴레이 초기화 실패: {e}")
            raise

    def on(self):
        """릴레이를 작동시킵니다 (접점 연결)"""
        if not self.relay.value:
            self.relay.on()
            print("릴레이 ON")

    def off(self):
        """릴레이 작동을 멈춥니다 (접점 분리)"""
        if self.relay.value:
            self.relay.off()
            print("릴레이 OFF")

    def toggle(self):
        """릴레이 상태를 반전시킵니다"""
        self.relay.toggle()
        print(f"릴레이 상태 반전 (현재: {'ON' if self.relay.value else 'OFF'})")

    def cleanup(self):
        """리소스 해제"""
        if hasattr(self, 'relay'):
            self.off() # 안전을 위해 끄고 종료
            self.relay.close()
            print("릴레이 리소스 해제 완료.")

# --- 테스트 실행부 ---
if __name__ == "__main__":
    # 대부분의 릴레이 모듈은 Low 신호에서 켜지므로 active_high=False가 기본입니다.
    # 만약 동작이 반대라면 True로 바꿔보세요.
    relay_ctrl = RelayController(pin=25, active_high=False)

    try:
        while True:
            relay_ctrl.on()
            time.sleep(2)
            relay_ctrl.off()
            time.sleep(2)
            
    except KeyboardInterrupt:
        print("\n사용자에 의해 종료됩니다.")
    finally:
        relay_ctrl.cleanup()
