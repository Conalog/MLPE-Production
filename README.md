# 양산 프로그램 (Raspberry Pi Jig)
제품 양산용 지그 내부에 설치되는 **라즈베리파이**에서 동작하는 양산 프로그램 프로젝트입니다.  
기본 언어는 **Python**이며, 양산 프로세스는 총 3단계로 구성됩니다.

---

## 양산 프로세스(3단계)
- **1단계**: 제품 생산 및 기본검증
- **2단계**: 1차 검증
- **3단계**: 마지막 검증(최종 검증)

> 각 단계별 코드/실행 스크립트는 이 저장소에서 함께 관리합니다(구성은 추후 확정).

---

## 운영 환경
- **OS**: Ubuntu Server 24.04.3 LTS
- **Hostname**: `conalog-jig-<ID>` (ID는 15글자의 영문/숫자 혼합 식별자)
- **Remote Access**: Tailscale (클라우드 VPN을 통한 원격 SSH 접속)
- **Python**: 3.12+ (Ubuntu 24.04 기본 버전 권장)
- **하드웨어**: 릴레이 / 버튼 / RGB LED / TM1637 / ADS1115 / J-Link / Stick

---

## 프로젝트 구조 및 실행 흐름
- **Supervisor**: `main.py`가 실행되고 `configs/jig.json`의 `stage` 값에 맞춰 `stage1/2/3` 모듈을 서브프로세스로 실행합니다.
- **Config 동기화**: `ConfigSyncThread`가 서버에서 jig 설정을 주기적으로 동기화하며 `stage` 변경을 감지합니다.
- **Stage 모듈**: 각 단계는 자체 Self-test → 버튼 대기 → 생산 시퀀스 순으로 동작합니다.
- **공통 요소**: `common/`(로깅/서버/브리지/유틸) + `utils/`(GPIO/ADC/LED/버튼/릴레이 등).

---

## 빠른 시작 (이미지 기반)
이 프로젝트는 **준비된 이미지(.img)** 를 SD카드에 기록해 사용하는 것을 전제로 합니다.  
사용자는 Ubuntu 24.04 Server LTS를 직접 설치하거나 별도 환경 구성 과정을 거치지 않습니다.

### 1) SD카드에 이미지 쓰기
제공된 이미지 파일을 SD카드에 기록합니다(Etcher 등 사용).

### 2) 호스트명 설정 (첫 부팅 전에)
라즈베리파이 기준 `/boot/firmware/hostname.txt` 파일에 아래 포맷으로 **한 줄** 작성합니다.

포맷:
```
conalog-jig-<15글자>
```

> 첫 부팅 시, 시스템이 `hostname.txt` 값을 읽어 호스트명을 자동 설정하고  
> 이 프로젝트가 자동 실행되도록 구성됩니다.

---

## 의존성
이미지에 모든 의존성이 포함되어 있어, 사용자가 별도로 설치할 필요는 없습니다.  
참고용으로 이미지 생성 시 사용한 명령어는 `docs/image_build_steps.md`에 보관합니다.

---

## 외부 서비스 및 네트워크
- **DB 서버**: PocketBase (로그 업로드 / jig 설정 동기화)  
  `configs/server.json`의 `url`, `collection` 사용
- **MQTT 브리지**: Solar Bridge (기본 `localhost:1883`)
- **타임존 자동 감지**: `configs/jig.json`의 `timezone`이 `auto`일 때 IP 기반 감지 사용

---

## 실행 방법
이제 루트 디렉토리에 있는 `main.py`를 통해 모든 단계를 통합하여 실행할 수 있습니다. `configs/jig.json`의 `stage` 값에 따라 자동으로 해당 단계가 시작됩니다.

```bash
# 기본 설정(configs/jig.json)으로 실행
python3 main.py

# 특정 설정 파일을 지정하여 실행
python3 main.py --jig-config configs/jig_special.json
```

### 단일 단계 실행
```bash
python3 -m stage1
python3 -m stage2
python3 -m stage3
```
> Supervisor 없이 단독 실행 시 환경 변수(`GPIOZERO_PIN_FACTORY=lgpio`)가 필요할 수 있습니다.

---

## 설정 파일
- `configs/jig.json`: **지그 식별자/제품/단계/타임존/ADC 스케일**  
  - `stage`: 1~3 단계 선택  
  - `timezone`: `"Asia/Seoul"` 또는 `"auto"`  
  - `label`: Stage3 라벨 설정(예: `preset`, `kc_no`, `authenticator`, `model`)
- `configs/io.json`: TM1637/릴레이/LED/버튼 핀맵(BCM)
- `configs/server.json`: DB 서버 타입/URL/컬렉션 + (선택) `bridge_host`, `bridge_port`
- `configs/adc_values.json`: 단계/보드별 ADC Raw 임계값
- `configs/label_profiles.json`: 라벨 크기/레이아웃 프리셋

> `configs/jig.json`은 서버 동기화로 덮어쓰기될 수 있습니다.

---

## 테스트 프레임워크 및 확장 가이드
모든 단계(1, 2, 3단계)의 테스트는 추상화된 구조를 따르며, 새로운 테스트 케이스를 쉽게 추가하고 관리할 수 있습니다.

### 전역 상태 관리 (`stageX/globals.py`)
테스트 과정에서 발견된 장치 정보나 공유 자원은 전역 변수를 통해 관리됩니다.
- `g.target_device`: 현재 테스트 중인 MLPE 장치 정보 (FICR, Address, Device ID, REQ_GET_INFO 결과 등). 시퀀스 시작 시마다 초기화됩니다.
- `g.bridge`: Solar Bridge와의 통신을 위한 `SolarBridgeClient` 객체. 앱 실행 시 한 번 생성되어 재사용됩니다.

### 테스트 케이스 구조 (`common/test_base.py`)
모든 테스트 클래스는 `TestCase` 추상 클래스를 상속받아 구현됩니다.
```python
class TestCase(ABC):
    @abstractmethod
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        # 결과는 {"code": int, "log": str} 형식의 dict로 반환
        pass
```

### 새로운 테스트 추가 방법
1. 해당 단계의 `steps.py` (또는 `self_test.py`)에 `TestCase`를 상속받는 클래스를 작성합니다.
2. `run()` 메서드 내에 로직을 구현합니다. 필요 시 `g.target_device`나 `g.bridge`를 활용합니다.
3. 시퀀스 실행 함수(예: `run_stage_test()`) 내의 `steps` 리스트에 해당 인스턴스를 추가합니다.

---

## 양산 프로세스(3단계) 상세 가이드
각 단계별 상세 가이드는 해당 폴더의 `README.md`를 참고하세요.

- [**1단계 상세 가이드 (생산 및 기본검증)**](stage1/README.md)
- [**2단계 상세 가이드 (1차 검증)**](stage2/README.md)
- [**3단계 상세 가이드 (최종 검증)**](stage3/README.md)
> Stage 2/3는 유선 연결이 없으므로 비콘 기반으로 장비를 선택합니다.  
> 선택 기준: **Vendor/Product 타입 일치** → **RSSI 기준**.

---

### 1-4. 자동 실행 설정 (systemd)
```ini
[Unit]
Description=Factory Jig Supervisor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/pi/production_jig
Environment=GPIOZERO_PIN_FACTORY=lgpio
ExecStart=/usr/bin/python3 /home/pi/production_jig/main.py
Restart=on-failure
RestartSec=1

[Install]
WantedBy=multi-user.target
```

---

## 현재 포함된 모듈
하드웨어 제어 및 공통 유틸리티 구성입니다.

- `common/solar_bridge.py`: Solar Bridge(Go MQTT) 통신 클라이언트
- `common/db_server.py`: 로그 전송 및 데이터베이스 인터페이스
- `utils/ads1115.py`: ADC 측정 유틸
- `utils/button.py`: 물리 버튼 인터페이스
- `utils/rgb_led.py`: 상태 표시 LED 제어
- `utils/tm1637.py`: 7-seg 디스플레이 제어

---

## 설정 및 로깅
- **로깅 정책**: 
    - 로컬: `logs/<stage>/YYYYMMDD/<stage>.jsonl` (JSONL 포맷으로 실시간 기록)
    - Supervisor: `logs/supervisor/YYYYMMDD/supervisor.jsonl`
    - 서버: `Self-test` 전체 또는 `Stage-test` 전체 완료 시점에 집계된 결과(`AggregatedResult`)를 한 번에 `push_log` 수행
- **캘리브레이션**: `configs/jig.json`의 `adc_scales` 필드를 통해 전압/전류 오프셋 조정

---

## 에러 코드
에러 코드는 `common/error_codes.py`에 정의되어 있으며, TM1637 표시/서버 로그에 동일하게 사용됩니다.

---

## 트러블슈팅
- **J-Link 인식 실패**: `probe-rs list` 결과 확인, udev 규칙 재로드
- **DB 서버 연결 실패**: `configs/server.json` URL/컬렉션 확인
- **MQTT 통신 실패**: `bridge_host`, `bridge_port` 및 브로커 상태 확인
- **ADS1115 미인식**: I2C 활성화(`/boot/firmware/config.txt`), 배선/주소 확인
- **프린터 미등록**: `lpinfo -v`, `lpstat -v` 결과 확인 (CUPS 설치 필요)

---

## 향후 과제 (참고)
- 미구현 테스트 항목 보강 (예: 입력 전원 확인, 제품 타입 판별 등)
- 시스템 일괄 종료/업데이트 시나리오 보강
- Stage 2/3 비콘 기반 장비 선택 시 오선택 방지(식별 강화/필터링 개선)
