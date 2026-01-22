# 2단계(최종 조립 및 검증) 상세 가이드

## 2-1. 전체 프로세스 흐름도
```mermaid
---
config:
  theme: mc
---
flowchart TD
    subgraph Boot_Phase["1. 환경 준비 및 시스템 초기화"]
        A1["인터넷 및 DB 서버 연결 확인 <br>(연결될 때까지 대기)"]
        A2["타임존 설정 및 부팅 로그 전송 <br>(1회성 수행)"]
        A1 --> A2
    end

    subgraph Self_Test_Phase["2. 하드웨어 자체 검사 (Self-test)"]
        direction TB
        B_Start((자체 검사 시작))
        
        B_GPIO{"1. GPIO 가용성 확인"}
        B_JigID{"2. Jig ID 정합성 확인"}
        B_Stick{"3. Stick 연결 확인"}
        
        B_Fail["에러 코드 표시 및 버튼 대기"]
        B_Ready["대기 상태 (White LED)"]

        B_Start --> B_GPIO
        
        B_GPIO -- OK --> B_JigID
        B_JigID -- OK --> B_Stick
        B_Stick -- OK --> B_Ready

        B_GPIO -- Fail --> B_Fail
        B_JigID -- Fail --> B_Fail
        B_Stick -- Fail --> B_Fail

        B_Fail -- "버튼 Push (Retry)" --> B_Start
    end

    subgraph Production_Phase["3. 2단계 검증 시퀀스 (버튼 입력 시)"]
        direction TB
        C_Start((시퀀스 시작))
        C_Neighbor{"1. 주변 장치 인식 (RSSI)"}
        C_Verify{"2. 장비 정합성 검증"}
        C_ADC_Pre{"3. ADC 확인 (Relay OFF)"}
        C_Relay_ON["4. Relay ON (RSD 해제)"]
        C_ADC_Post{"5. ADC 확인 (Relay ON)"}
        C_RSD1{"6-1. RSD1 ON"}
        C_ADC_RSD1{"6-2. ADC 확인 (RSD1)"}
        C_RSD2{"6-3. RSD1+2 ON"}
        C_ADC_RSD2{"6-4. ADC 확인 (RSD1+2)"}
        C_RSD_OFF{"6-5. RSD All OFF"}
        C_Relay_OFF["7. Relay OFF (안전)"]
        
        C_Result["결과 서버 전송 및 로그 기록"]
        C_Fail["에러 표시 (Red LED) & 버튼 대기"]
        C_Done((완료))

        C_Start --> C_Neighbor
        
        C_Neighbor -- OK --> C_Verify
        C_Verify -- OK --> C_ADC_Pre
        C_ADC_Pre -- OK --> C_Relay_ON
        C_Relay_ON -- OK --> C_ADC_Post
        C_ADC_Post -- OK --> C_RSD1
        C_RSD1 -- OK --> C_ADC_RSD1
        C_ADC_RSD1 -- OK --> C_RSD2
        C_RSD2 -- OK --> C_ADC_RSD2
        C_ADC_RSD2 -- OK --> C_RSD_OFF
        C_RSD_OFF -- OK --> C_Relay_OFF
        C_Relay_OFF --> C_Result
        
        C_Neighbor -- Fail --> C_Fail
        C_Verify -- Fail --> C_Fail
        C_ADC_Pre -- Fail --> C_Fail
        C_Relay_ON -- Fail --> C_Fail
        C_ADC_Post -- Fail --> C_Fail
        C_RSD1 -- Fail --> C_Fail
        C_ADC_RSD2 -- Fail --> C_Fail
        
        C_Fail -- "버튼 Push (Acknowledge)" --> C_Done
        C_Result --> C_Done
    end

    A2 --> B_Start
    B_Ready -- "테스트 버튼 Push" --> C_Start
    C_Done -- "완료 후 복귀" --> B_Ready

    style Boot_Phase fill:#f5f5f5,stroke:#333
    style Self_Test_Phase fill:#fff3e0,stroke:#e65100
    style Production_Phase fill:#e1f5fe,stroke:#01579b
    style B_Fail fill:#ffebee,stroke:#c62828
    style B_Ready fill:#e8f5e9,stroke:#2e7d32
    style C_Fail fill:#ffebee,stroke:#c62828
```

## 2-2. 자체 검사 (Self-test) 상세
부팅 직후 환경 준비 과정을 거쳐 자동으로 수행됩니다. Stage 2에서는 J-Link 및 ADS1115 점검이 생략됩니다.

- **Phase 1 (환경 준비)**: 인터넷 및 DB 서버 연결 확인 (실패 시 에러 코드 6, 7 표시)
- **Phase 2 (시스템 초기화)**: 타임존 설정 및 부팅 로그(`stage2.boot`) 1회 전송
- **Phase 3 (하드웨어 점검)**: GPIO, Jig ID, Stick 연결 상태 확인
- **실패 시 처리**: 에러 코드를 표시하고 사용자의 재시도(버튼) 대기. 버튼 클릭 시 점검 단계만 재시작

## 2-3. 검증 시퀀스 상세 (버튼 동작)
사용자가 테스트 버튼을 누르면 시작됩니다. Stage 2는 펌웨어 업로드 과정이 없으며, 주변 장치 검색 및 MLPE ADC Raw 데이터 검증을 수행합니다.

1. **주변 장치 인식**: Neighbor List 초기화 후 일정 시간 대기, RSSI가 가장 낮은 장치를 타겟으로 자동 선택
2. **장비 정합성 검증**: 선택된 장치가 현재 테스트 대상 보드가 맞는지 추가 검증(자리 마련)
3. **ADC 확인 (Relay OFF)**: MLPE 내부 ADC Raw 값(Vin1, Vin2, Vout)이 설정된 범위 내에 있는지 확인
4. **Relay ON**: 지그의 릴레이를 활성화하여 제품에 전원을 인가하고 RSD 상태를 변경할 준비 수행
5. **ADC 확인 (Relay ON)**: 릴레이 활성화 직후의 ADC Raw 값 및 출력 전류(Iout) 확인
6. **RSD 상태별 검증**: MQTT 명령을 통해 MLPE의 내부 RSD 상태를 변경하며 전압 변화 확인
    - **RSD1 ON**: RSD1만 작동 시 전압 확인
    - **RSD1+2 ON**: 모든 RSD 작동 시 전압 확인
    - **RSD All OFF**: 모든 RSD 해제 상태로 복귀
7. **Relay OFF**: 테스트 종료 후 안전을 위해 지그 릴레이를 다시 비활성화
8. **결과 처리**: 모든 단계의 실행 로그를 서버로 전송
- **공통 사항**: 
    - 판정 기준은 `configs/adc_values.json`에서 통합 관리됩니다.
    - 모든 ADC 검증은 전압으로 변환되지 않은 **Raw ADC Count**를 기준으로 수행됩니다.
