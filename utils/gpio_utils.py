import lgpio
import os

def find_gpio_chip():
    """유효한 GPIO 칩 인덱스를 검색합니다."""
    # 1. 일반적인 후보 인덱스들 (0: Pi 4 이하, 4: Pi 5, 1: 일부 Ubuntu)
    candidates = [0, 4, 1]
    
    # 2. /dev/gpiochip* 파일을 직접 스캔하여 후보군 확장
    try:
        dev_chips = [int(f.replace('gpiochip', '')) for f in os.listdir('/dev') if f.startswith('gpiochip')]
        for c in sorted(dev_chips):
            if c not in candidates:
                candidates.append(c)
    except Exception:
        pass

    for idx in candidates:
        try:
            h = lgpio.gpiochip_open(idx)
            lgpio.gpiochip_close(h)
            return idx
        except Exception:
            continue
            
    raise RuntimeError("유효한 GPIO 칩을 찾을 수 없습니다. (lgpio가 설치되어 있고 /dev/gpiochip* 접근 권한이 있는지 확인하세요)")
