from __future__ import annotations
import json
import threading
import time
import logging
import paho.mqtt.client as mqtt
from typing import Any, Optional

class SolarBridgeClient:
    """
    Solar Bridge (Go MQTT Server)와 통신하기 위한 클라이언트.
    지속적인 연결(Persistent Connection)을 유지하여 통신 안정성을 확보합니다.
    """
    def __init__(self, host: str = "localhost", port: int = 1883, timeout: float = 1.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._client = mqtt.Client()
        self._client.on_message = self._on_message
        self._client.on_connect = self._on_connect
        self._client.on_subscribe = self._on_subscribe
        
        self._stick_list: list[dict[str, Any]] = []
        self._neighbor_map: dict[str, list[dict[str, Any]]] = {}
        self._device_info_map: dict[str, dict[str, Any]] = {}
        self._cmd_results: dict[str, str] = {}
        self._responses: dict[str, Any] = {}
        self._mlpe_data: dict[str, Any] = {}
        self._adc_data: dict[str, list[dict[str, Any]]] = {}
        self._clear_neighbors_results: dict[str, bool] = {}
        self._upper_id_map: dict[str, int] = {}  # Map lower 4-byte ID to upper 2-byte ID
        
        self._response_event = threading.Event()
        self._result_event = threading.Event()
        self._connected_event = threading.Event()
        self._subscribed_topics: set[str] = set()
        self._subscribe_event = threading.Event()
        self._target_subscribe_topic: Optional[str] = None

    def start(self):
        """MQTT 클라이언트를 시작하고 연결될 때까지 대기합니다."""
        self._client.connect(self.host, self.port, keepalive=60)
        self._client.loop_start()
        if not self._connected_event.wait(timeout=self.timeout):
            raise ConnectionError(f"Failed to connect to {self.host}:{self.port}")
        
        # 기본 브릿지 및 단순 API 채널 구독
        self._subscribe_sync([
            "solar/bridge/rx", 
            "solar/simple/rx",
            "solar/mlpe/+/rx",
            "solar/stick/+/rx",
            "solar/complex/+/rx"
        ])

    def stop(self):
        """연결을 종료합니다."""
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected_event.set()

    def _on_subscribe(self, client, userdata, mid, granted_qos):
        self._subscribe_event.set()

    def _subscribe_sync(self, topics: list[str]):
        """구독이 브로커에서 승인될 때까지 동기적으로 대기합니다."""
        new_topics = [t for t in topics if t not in self._subscribed_topics]
        if not new_topics:
            return
        
        self._subscribe_event.clear()
        for t in new_topics:
            self._client.subscribe(t)
            self._subscribed_topics.add(t)
        
        self._subscribe_event.wait(timeout=self.timeout)

    def _normalize_id(self, device_id: str) -> str:
        """ID를 일관된 형식(0x + 8자리 대문자)으로 정규화합니다."""
        if not device_id:
            return "0x00000000"
        
        clean = str(device_id).upper()
        if clean.startswith("0X"):
            clean = clean[2:]
        
        # 6바이트(12자리) 이상의 주소인 경우 하위 4바이트(8자리)만 추출
        if len(clean) > 8:
            clean = clean[-8:]
            
        return f"0x{clean.zfill(8)}"

    def _on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload_str = msg.payload.decode()
            data = json.loads(payload_str)
            
            if "solar/bridge" in topic or "solar/simple" in topic:
                logging.debug(f"[MQTT] RX Topic: {topic}, Payload: {payload_str[:200]}")
            
            # 1. Bridge 관리 응답
            if topic == "solar/bridge/rx":
                msg_type = data.get("type")
                if msg_type == "STICK_LIST":
                    sticks = data.get("sticks", [])
                    for s in sticks:
                        # Reconstruct version string for backward compatibility (e.g. "1.2.3")
                        if "major" in s and "minor" in s and "patch" in s:
                            s["version"] = f"{s['major']}.{s['minor']}.{s['patch']}"
                    self._stick_list = sticks
                    self._response_event.set()
                elif msg_type == "SUCCESS" and data.get("command") == "GET_NEIGHBORS":
                    # Bridge API의 GET_NEIGHBORS 응답 처리
                    res_data = data.get("data", {})
                    self._neighbor_map["last"] = res_data.get("neighbors", [])
                    self._response_event.set()
                elif msg_type == "SUCCESS" and data.get("command") == "CLEAR_NEIGHBORS":
                    self._response_event.set()

            # 2. Simple API 응답
            elif topic == "solar/simple/rx":
                cmd_name = data.get("command")
                res_payload = data.get("response", {})
                
                # Protobuf 응답 평탄화(Flatten) 및 하위 호환성 처리
                if isinstance(res_payload, dict):
                    # 1. Protobuf 필드가 중첩되어 있으면 하위로 진입
                    if "Protobuf" in res_payload:
                        res_payload = res_payload["Protobuf"]
                    
                    if isinstance(res_payload, dict):
                        # 2. resp_... 또는 Resp... 로 시작하는 메시지 응답 객체 찾아서 평탄화
                        # 예: resp_get_mppt_status -> 내부의 mppt, max_duty 등을 상위로 병합
                        inner_data = None
                        for k, v in res_payload.items():
                            if (k.lower().startswith("resp_") or k.lower().startswith("resp")) and isinstance(v, dict):
                                inner_data = v
                                break
                        
                        if inner_data:
                            res_payload.update(inner_data)
                    
                    # 3. 특정 명령별 추가 하위 호환성 처리
                    cmd_val = res_payload.get("cmd")
                    if cmd_val in ["RESP_GET_INFO", 103]:
                        v_raw = res_payload.get("version", 0)
                        if v_raw:
                            res_payload.update({
                                "vid": (v_raw >> 28) & 0x0F,
                                "pid": (v_raw >> 20) & 0x0F,
                                "version_unpacked": f"{(v_raw >> 14) & 0x3F}.{(v_raw >> 8) & 0x3F}.{v_raw & 0xFF}"
                            })
                        if "id_high" in res_payload:
                            res_payload["upper_id"] = res_payload["id_high"]

                tid = self._normalize_id(data.get("target_id") or "0")
                if tid not in self._mlpe_data: self._mlpe_data[tid] = {}
                
                # 결과 상태 확인
                if data.get("type") == "ERROR" or data.get("status") == "FAILED":
                    self._mlpe_data[tid][cmd_name] = {"status": "FAILED", "message": data.get("message")}
                else:
                    # BEACON_RAW_DATA인 경우 추가 처리
                    if cmd_name == "BEACON_RAW_DATA":
                        beacon = res_payload.get("beacon_raw_data") or res_payload
                        if isinstance(beacon, dict):
                            self._unpack_beacon_data(tid, beacon)
                            res_payload = beacon # 평탄화된 데이터로 교체

                    self._mlpe_data[tid][cmd_name] = res_payload
                
                # 동기 대기용 결과 저장 및 이벤트 세트
                self._responses[cmd_name] = self._mlpe_data[tid][cmd_name]
                self._response_event.set()

            # 3. MLPE 데이터 (BEACON_RAW_DATA 등)
            elif "solar/mlpe" in topic and "/rx" in topic:
                tid = self._normalize_id(topic.split("/")[2])
                mlpe_pkt = data.get("mlpe_packet", {})
                pb = mlpe_pkt.get("Protobuf", {})
                
                cmd_name = pb.get("cmd")
                if cmd_name == "BEACON_RAW_DATA":
                    beacon = pb.get("beacon_raw_data") or pb
                    self._unpack_beacon_data(tid, beacon)
                    # 일반 데이터로도 저장
                    if tid not in self._mlpe_data: self._mlpe_data[tid] = {}
                    self._mlpe_data[tid]["BEACON_RAW_DATA"] = beacon

            # 4. Complex API 상태 (필요 시)
            elif "solar/complex" in topic:
                status = data.get("status")
                if status in ["SUCCESS", "COMPLETED"]:
                    self._response_event.set()

        except Exception as e:
            logging.error(f"[SolarBridge] Error parsing message: {e}")

    def _unpack_beacon_data(self, tid: str, beacon: dict):
        """BEACON_RAW_DATA 패킷에서 ADC 값을 추출하고 버퍼에 저장합니다."""
        # ADC 데이터 언패킹 (16-bit units)
        # raw_0 = (vin1_raw << 16) | vin2_raw
        # raw_1 = (iout_raw << 16) | vout_raw
        r0 = beacon.get("raw_0", 0)
        r1 = beacon.get("raw_1", 0)
        
        if r0 > 65535: # 패킹된 경우
            beacon["vin1_raw"] = r0 >> 16
            beacon["vin2_raw"] = r0 & 0xFFFF
        else: # 단일 값인 경우
            beacon["vin1_raw"] = r0
            beacon["vin2_raw"] = 0
            
        if r1 > 65535: # 패킹된 경우
            beacon["iout_raw"] = r1 >> 16
            beacon["vout_raw"] = r1 & 0xFFFF
        else: # 단일 값 또는 수집 전인 경우
            beacon["iout_raw"] = 0
            beacon["vout_raw"] = r1
        
        if tid not in self._adc_data: self._adc_data[tid] = []
        # 중복 방지 (uptime 등으로 체크 가능하나 여기서는 단순 추가)
        self._adc_data[tid].append(beacon)

    def list_sticks(self, logger=None) -> list:
        self._stick_list = []
        self._response_event.clear()
        
        self._client.publish("solar/bridge/tx", json.dumps({"command": "LIST_STICKS"}))
        
        if self._response_event.wait(timeout=self.timeout):
            return self._stick_list
        else:
            if logger:
                logger.warning("Timeout waiting for STICK_LIST response")
            return []

    def dump_adc(self, target_id: str, stick_uid: str, duration: float = 1.0, logger=None) -> list:
        """BEACON_RAW_DATA 명령을 폴링하여 ADC 데이터를 수집합니다."""
        tid_fmt = self._normalize_id(target_id)
        self._adc_data[tid_fmt] = []
        
        if logger: logger.info(f"[{target_id}] Starting ADC collection via BEACON_RAW_DATA polling for {duration}s")
        
        start_time = time.time()
        while time.time() - start_time < duration:
            # 타임아웃은 짧게 가져가서 빈번하게 요청 가능하도록 함 (500ms 이내 응답 예상)
            self._run_command(stick_uid, target_id, "BEACON_RAW_DATA", {}, logger=logger, cmd_timeout=0.6, attempts=1)
            
            # 수집 주기 조절 (주기적으로 요청)
            # 브릿지/장치 성능을 고려하여 0.2초 정도 대기
            time.sleep(0.2)
        
        samples = self._adc_data.get(tid_fmt, [])
        if logger: logger.info(f"[{target_id}] ADC collection finished. Collected {len(samples)} samples.")
        
        if not samples and logger:
            logger.warning(f"[SolarBridge] Failed to collect any ADC samples for {tid_fmt}")
        return samples

    def get_neighbors(self, stick_uid: str, target_id: str = "0", logger=None) -> list:
        """Bridge API를 사용하여 이웃 노드 정보를 가져옵니다."""
        self._response_event.clear()
        self._neighbor_map.pop("last", None)
        
        try:
            tid_val = int(target_id, 16) if target_id.lower().startswith("0x") else int(target_id)
        except ValueError:
            tid_val = 0
            
        payload = {
            "command": "GET_NEIGHBORS",
            "stick_uid": stick_uid,
            "target_id": tid_val
        }
        self._client.publish("solar/bridge/tx", json.dumps(payload))
        
        if self._response_event.wait(timeout=5.0): # Pagination 등으로 인해 타임아웃 넉넉히
            return self._neighbor_map.get("last", [])
        return []

    def clear_neighbors(self, stick_uid: str, target_id: str = "0", logger=None) -> bool:
        self._response_event.clear()
        try:
            tid_val = int(target_id, 16) if target_id.lower().startswith("0x") else int(target_id)
        except ValueError:
            tid_val = 0
            
        self._client.publish("solar/bridge/tx", json.dumps({
            "command": "CLEAR_NEIGHBORS", 
            "stick_uid": stick_uid,
            "target_id": tid_val
        }))
        return self._response_event.wait(timeout=self.timeout)

    def get_device_info(self, target_id: str, stick_uid: str, logger=None) -> Optional[dict]:
        return self._run_command(stick_uid, target_id, "REQ_GET_INFO", {}, logger=logger)

    def req_shutdown(self, target_id: str, stick_uid: str, rsd1=True, rsd2=True, logger=None) -> Optional[dict]:
        # ReqShutdown Protobuf fields: rsd1, rsd2, groupNum1
        # 트리거형 명령이므로 1회만 시도하여 지연 방지
        args = {"rsd1": rsd1, "rsd2": rsd2, "groupNum1": 0xFFFFFFFF}
        return self._run_command(stick_uid, target_id, "REQ_SHUTDOWN", args, logger=logger, attempts=1)

    def set_mesh_config(self, target_id: str, stick_uid: str, asp_interval: int = 200, tx_pwr: int = -20, logger=None) -> Optional[dict]:
        """메쉬 설정을 변경합니다. (기본: Channel 39, ASP 200ms, TxPwr -20dBm, Group 0xFF)"""
        args = {
            "l1": {"channel": 39, "txPwr": tx_pwr},
            "l2": {"aspInterval": asp_interval},
            "l3": {"meshGroupId": 0xff, "relayOption": 0, "relayRatio": 50}
        }
        return self._run_command(stick_uid, target_id, "REQ_SET_MESH_CONFIG", args, logger=logger)

    def get_mppt_status(self, target_id: str, stick_uid: str, logger=None) -> Optional[dict]:
        return self._run_command(stick_uid, target_id, "REQ_GET_MPPT_STATUS", {}, logger=logger)

    def enable_mppt(self, target_id: str, stick_uid: str, enable: bool = True, logger=None) -> Optional[dict]:
        args = {"status": enable}
        return self._run_command(stick_uid, target_id, "REQ_ENABLE_MPPT", args, logger=logger, attempts=1)

    def set_mppt_config(self, target_id: str, stick_uid: str, max_duty=None, min_limit=None, max_limit=None, bypass_condition=None, logger=None) -> Optional[dict]:
        # Protobuf 필드 이름(CamelCase)에 맞춰 아규먼트 생성
        # 0xFFFFFFFF는 변경하지 않음을 의미 (서버/디바이스 스펙)
        args = {
            "maxDuty": max_duty if max_duty is not None else 0xFFFFFFFF,
            "dutyMinLimit": min_limit if min_limit is not None else 0xFFFFFFFF,
            "dutyMaxLimit": max_limit if max_limit is not None else 0xFFFFFFFF,
            "bypassCondition": bypass_condition if bypass_condition is not None else False
        }
        return self._run_command(stick_uid, target_id, "REQ_SET_MPPT_CONFIG", args, logger=logger)

    def _run_command(self, stick_uid: str, target_id: str, cmd_name: str, args: dict, logger=None, cmd_timeout=None, attempts=2) -> Optional[dict]:
        tid_norm = self._normalize_id(target_id)
        
        # 새로운 Simple API 페이로드 구성
        is_broadcast = target_id in ["0", "0xFFFFFFFF", "0xffffffff"]
        route = 1 if is_broadcast else 2
        
        payload = {
            "stick_uid": stick_uid,
            "command": cmd_name,
            "target_id": tid_norm,
            "routing_type": route,
            "args": args
        }

        wait_timeout = cmd_timeout if cmd_timeout is not None else self.timeout

        max_attempts = attempts
        for attempt in range(1, max_attempts + 1):
            self._response_event.clear()
            self._responses.pop(cmd_name, None)
            
            if logger:
                logger.debug(f"[SolarBridge] TX {cmd_name} to {target_id} (Attempt {attempt}/{max_attempts})")
            
            self._client.publish("solar/simple/tx", json.dumps(payload))

            if is_broadcast and "GET" not in cmd_name:
                return {"status": "SUCCESS"}

            if self._response_event.wait(timeout=wait_timeout):
                res = self._mlpe_data.get(tid_norm, {}).get(cmd_name) or self._responses.get(cmd_name)
                if isinstance(res, dict) and res.get("status") == "FAILED":
                    if logger: logger.warning(f"[SolarBridge] {cmd_name} failed: {res.get('message')}")
                    continue # Retry on failure
                return res
            
            if logger:
                logger.warning(f"[SolarBridge] {cmd_name} timeout for {target_id} (Attempt {attempt})")
        
        return None
