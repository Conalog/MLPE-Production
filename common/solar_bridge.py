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
    각 메소드는 독립적인 연결(self-contained connection)을 사용하여 안정성을 보장합니다.
    """
    def __init__(self, host: str = "localhost", port: int = 1883, timeout: float = 1.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._client = mqtt.Client()
        self._client.on_message = self._on_message
        
        self._stick_list: list[dict[str, Any]] = []
        self._neighbor_map: dict[str, list[dict[str, Any]]] = {} # stick_id -> neighbors
        self._device_info_map: dict[str, dict[str, Any]] = {}   # device_id -> info
        
        # 로우 레벨 명령 결과를 위한 상태 저장
        self._cmd_results: dict[str, str] = {}
        self._responses: dict[str, Any] = {}
        self._mlpe_data: dict[str, Any] = {}
        self._adc_data: dict[str, list[dict[str, Any]]] = {}
        
        self._response_event = threading.Event()
        self._result_event = threading.Event()

    def _on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            data = json.loads(msg.payload.decode())
            
            # 1. Bridge 관리 응답 (solar/bridge/rx)
            if topic == "solar/bridge/rx":
                msg_type = data.get("type")
                
                # LIST_STICKS 응답
                if msg_type == "STICK_LIST" or isinstance(data, list) or (isinstance(data, dict) and "sticks" in data):
                    if isinstance(data, list):
                        self._stick_list = data
                    elif isinstance(data, dict):
                        self._stick_list = data.get("sticks", [])
                    self._response_event.set()
                
                # GET_NEIGHBORS 응답 (Bridge API 버전)
                parsed_data = data.get("parsed_data", {})
                if parsed_data.get("cmd_name") == "RESP_GET_NEIGHBORS":
                    stick_id = data.get("stick_id")
                    res_payload = parsed_data.get("payload", {})
                    neighbors = res_payload.get("neighbors", [])
                    if stick_id:
                        self._neighbor_map[stick_id] = neighbors
                    self._response_event.set()

            # 2. 로우 레벨 결과 알림 (solar/device/<UID>/result)
            elif "/result" in topic:
                cmd_name = data.get("command")
                status = data.get("status")
                if cmd_name:
                    self._cmd_results[cmd_name] = status
                    self._result_event.set()

            # 3. 로우 레벨 데이터 응답 (RX)
            elif "/rx" in topic:
                parsed = data.get("parsed_data", {})
                cmd_name = parsed.get("cmd_name")
                
                if cmd_name:
                    res_payload = parsed.get("payload", {})
                    
                    # Version Unpacking (VID, PID, etc)
                    if cmd_name in ["RESP_GET_INFO", "BEACON_RAW_DATA"]:
                        v_raw = res_payload.get("version", 0)
                        if v_raw:
                            vid = (v_raw >> 28) & 0x0F
                            pid = (v_raw >> 20) & 0x0F
                            major = (v_raw >> 16) & 0x0F
                            minor = (v_raw >> 8) & 0xFF
                            patch = v_raw & 0xFF
                            res_payload["vid"] = vid
                            res_payload["pid"] = pid
                            res_payload["version_unpacked"] = f"{major}.{minor}.{patch}"

                    self._responses[cmd_name] = res_payload
                    
                    # ID 추출 (MLPE ID or L3 Source or Topic Fallback)
                    target_id = data.get("mlpe_id")
                    if not target_id:
                        target_id = data.get("l3_header", {}).get("src")
                    
                    if not target_id and "mlpe/" in topic:
                        # Topic: solar/mlpe/0x12345678/rx
                        parts = topic.split("/")
                        if len(parts) >= 3:
                            target_id = parts[2]
                    
                    if target_id:
                        self._mlpe_data[target_id.upper()] = res_payload
                    
                    if cmd_name.startswith("RESP_"):
                        self._response_event.set()
                
            # 4. 고속 ADC 데이터 (solar/mlpe/<ID>/adc)
            elif "/adc" in topic:
                # High-Level Feature: solar/mlpe/<ID>/adc
                target_id = data.get("mlpe_id")
                if not target_id:
                    parts = topic.split("/")
                    if len(parts) >= 3:
                        target_id = parts[2]
                
                if target_id:
                    target_id_upper = target_id.upper()
                    if target_id_upper not in self._adc_data:
                        self._adc_data[target_id_upper] = []
                    self._adc_data[target_id_upper].append(data)

            # 5. 스마트 기능 상태 (solar/feature/<UID>/status)
            elif "/status" in topic:
                # Smart Feature Status: solar/feature/<UID>/status
                feature = data.get("feature")
                status = data.get("status")
                if feature:
                    self._cmd_results[feature] = status

        except Exception:
            pass

    def list_sticks(self, logger: Optional[logging.Logger] = None) -> list[dict[str, Any]]:
        """연결된 스틱 목록을 조회합니다 (Bridge API)."""
        self._stick_list = []
        self._response_event.clear()

        try:
            self._client.connect(self.host, self.port, keepalive=60)
            # Subscribe to bridge, device results, and MLPE responses
            self._client.subscribe("solar/bridge/rx")
            self._client.subscribe("solar/device/+/result")
            self._client.subscribe("solar/mlpe/+/rx")
            self._client.subscribe("solar/mlpe/+/adc")
            self._client.subscribe("solar/feature/+/status")
            self._client.loop_start()

            self._client.publish("solar/bridge/tx", json.dumps({"type": "LIST_STICKS"}))

            wait_ok = self._response_event.wait(timeout=self.timeout)
            
            self._client.loop_stop()
            self._client.disconnect()

            return self._stick_list if wait_ok else []
        except Exception as e:
            if logger: logger.error(f"list_sticks failed: {e}")
            return []

    def dump_adc(self, target_id: str, stick_uid: str, duration: float = 1.0, logger=None) -> list:
        """
        DUMP_RAW_ADC 하이레벨 기능을 사용하여 특정 장치의 ADC 데이터를 수집합니다.
        """
        target_id_upper = target_id.upper()
        if target_id_upper.startswith("0X"):
            target_id_clean = target_id_upper[2:]
        else:
            target_id_clean = target_id_upper
        
        target_id_fmt = f"0x{target_id_clean}"

        payload = {
            "command": "DUMP_RAW_ADC",
            "args": {
                "target_id": target_id_fmt,
                "duration": duration
            }
        }
        topic = f"solar/feature/{stick_uid}/tx"

        self._client.connect(self.host, self.port, 60)
        self._client.loop_start()

        try:
            # Subscribe to necessary topics
            self._client.subscribe(f"solar/mlpe/{target_id_fmt}/adc")
            self._client.subscribe(f"solar/feature/{stick_uid}/status")
            
            # 기존 데이터 클리어
            self._adc_data[target_id_fmt.upper()] = []
            self._cmd_results["DUMP_RAW_ADC"] = None

            if logger: logger.info(f"Sending DUMP_RAW_ADC to {target_id_fmt} via {stick_uid} (duration={duration}s)")
            self._client.publish(topic, json.dumps(payload))

            # 데이터 수집 대기 (duration + 여유 시간)
            end_time = time.time() + duration + 2.0
            while time.time() < end_time:
                # 상태가 SUCCESS로 변했거나 duration이 지났는지 확인
                if self._cmd_results.get("DUMP_RAW_ADC") == "SUCCESS":
                    # SUCCESS가 오더라도 데이터 패킷이 다 올 때까지 조금 더 기다림
                    if time.time() > (end_time - 1.0):
                        break
                
                if self._cmd_results.get("DUMP_RAW_ADC") == "FAILED":
                    if logger: logger.error(f"DUMP_RAW_ADC failed for {target_id_fmt}")
                    break
                    
                time.sleep(0.1)

            data_count = len(self._adc_data.get(target_id_fmt.upper(), []))
            if logger: logger.info(f"DUMP_RAW_ADC finished. Collected {data_count} samples.")
            
            return self._adc_data.get(target_id_fmt.upper(), [])

        finally:
            self._client.loop_stop()
            self._client.disconnect()

    def get_neighbors(self, stick_id: str, logger: Optional[logging.Logger] = None) -> list[dict[str, Any]]:
        """주변 노드 검색 (Low-Level Device API 사용 버전)"""
        # 이웃 검색은 Stick(ID: 0)에게 요청하는 로우 레벨 명령으로 수행
        res = self._run_command(stick_id, "0", "REQ_GET_NEIGHBORS", {}, logger=logger)
        if res:
            return res.get("neighbors", [])
        return []

    def get_device_info(self, target_id: str, stick_id: str, logger: Optional[logging.Logger] = None) -> Optional[dict[str, Any]]:
        """장치 정보 조회 (Low-Level Device API)"""
        return self._run_command(stick_id, target_id, "REQ_GET_INFO", {}, logger=logger)

    def req_shutdown(self, target_id: str, stick_uid: str, rsd1: bool = True, rsd2: bool = True, logger: Optional[logging.Logger] = None) -> Optional[dict[str, Any]]:
        """REQ_SHUTDOWN 명령 전송 (Low-Level Device API)"""
        args = {
            "target_id": target_id,
            "route": 2,
            "rsd1": rsd1,
            "rsd2": rsd2,
            "group_num1": 0xFFFFFFFF  # 4294967295, 고정값 요구사항 반영
        }
        return self._run_command(stick_uid, target_id, "REQ_SHUTDOWN", args, logger=logger)

    def _run_command(self, stick_uid: str, target_id: str, cmd_name: str, args: dict, logger: Optional[logging.Logger] = None) -> Optional[dict[str, Any]]:
        """Low-Level Device API 실행 로직 (self-contained connection)"""
        target_id_upper = target_id.upper()
        resp_name = cmd_name.replace("REQ_", "RESP_")
        
        self._cmd_results[cmd_name] = None
        if resp_name in self._responses:
            del self._responses[resp_name]
        
        try:
            self._client.connect(self.host, self.port, keepalive=60)
            
            # 구독
            self._client.subscribe(f"solar/device/{stick_uid}/rx")
            self._client.subscribe(f"solar/device/{stick_uid}/result")
            if target_id != "0":
                self._client.subscribe(f"solar/mlpe/{target_id}/rx")
            
            self._client.loop_start()

            # 명령 구성
            args["target_id"] = target_id
            if "route" not in args:
                args["route"] = 2 if target_id not in ["0", "0xFFFFFFFF"] else 1
            
            payload = {"command": cmd_name, "args": args}
            
            if logger:
                logger.info(f"Sending Low-Level cmd: {cmd_name} to {target_id} via {stick_uid}")
            
            self._client.publish(f"solar/device/{stick_uid}/tx", json.dumps(payload))

            # 대기
            result_data = None
            end_time = time.time() + self.timeout
            while time.time() < end_time:
                # 1. 실제 데이터 패킷 확인 (가장 확실함)
                if "GET" in cmd_name:
                    if resp_name in self._responses:
                        result_data = self._responses[resp_name]
                        break
                    if target_id != "0" and target_id_upper in self._mlpe_data:
                        result_data = self._mlpe_data[target_id_upper]
                        break
                
                # 2. 브릿지 ACK 확인
                if self._cmd_results.get(cmd_name) == "SUCCESS":
                    if "GET" not in cmd_name:
                        result_data = {"status": "SUCCESS"}
                        break
                
                # 오류 응답 확인
                if self._cmd_results.get(cmd_name) and self._cmd_results.get(cmd_name) != "SUCCESS":
                    if logger: logger.warning(f"Cmd {cmd_name} failed: {self._cmd_results.get(cmd_name)}")
                    break
                
                time.sleep(0.1)

            self._client.loop_stop()
            self._client.disconnect()
            
            return result_data
        except Exception as e:
            if logger: logger.error(f"Command {cmd_name} failed: {e}")
            return None
