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
    def __init__(self, host: str = "localhost", port: int = 1883, timeout: float = 2.0):
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
        
        # 기본 브릿지 채널 구독
        self._subscribe_sync(["solar/bridge/rx", "solar/device/+/result", "solar/feature/+/status"])

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
        """ID를 일관된 형식(0x + 대문자)으로 정규화합니다."""
        clean = device_id.upper()
        if clean.startswith("0X"):
            clean = clean[2:]
        return f"0x{clean}"

    def _on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            data = json.loads(msg.payload.decode())
            
            # 1. Bridge 관리 응답
            if topic == "solar/bridge/rx":
                parsed_data = data.get("parsed_data", {})
                msg_type = data.get("type")
                
                if msg_type == "STICK_LIST" or isinstance(data, list) or "sticks" in data:
                    self._stick_list = data if isinstance(data, list) else data.get("sticks", [])
                    self._response_event.set()
                elif parsed_data.get("cmd_name") == "RESP_GET_NEIGHBORS":
                    sid = data.get("stick_id")
                    if sid: self._neighbor_map[sid] = parsed_data.get("payload", {}).get("neighbors", [])
                    self._response_event.set()
                elif parsed_data.get("cmd_name") == "RESP_CLEAR_NEIGHBORS":
                    sid = data.get("stick_id")
                    if sid: self._clear_neighbors_results[sid] = parsed_data.get("payload", {}).get("success", False)
                    self._response_event.set()

            # 2. 로우 레벨 결과
            elif "/result" in topic:
                cmd_name = data.get("command")
                if cmd_name:
                    self._cmd_results[cmd_name] = data.get("status")
                    self._result_event.set()

            # 3. 데이터 응답 (RX)
            elif "/rx" in topic:
                parsed = data.get("parsed_data", {})
                cmd_name = parsed.get("cmd_name")
                if cmd_name:
                    res_payload = parsed.get("payload", {})
                    if cmd_name in ["RESP_GET_INFO", "BEACON_RAW_DATA"]:
                        v_raw = res_payload.get("version", 0)
                        if v_raw:
                            res_payload.update({
                                "vid": (v_raw >> 28) & 0x0F, "pid": (v_raw >> 20) & 0x0F,
                                "version_unpacked": f"{(v_raw >> 16) & 0x0F}.{(v_raw >> 8) & 0xFF}.{v_raw & 0xFF}"
                            })
                    self._responses[cmd_name] = res_payload
                    tid = self._normalize_id(data.get("mlpe_id") or data.get("l3_header", {}).get("src") or topic.split("/")[2])
                    self._mlpe_data[tid] = res_payload
                    if cmd_name.startswith("RESP_"): self._response_event.set()
                
            # 4. 고속 ADC 데이터
            elif "/adc" in topic:
                tid = self._normalize_id(data.get("mlpe_id") or topic.split("/")[2])
                if tid not in self._adc_data: self._adc_data[tid] = []
                self._adc_data[tid].append(data)

            # 5. 스마트 기능 상태
            elif "/status" in topic:
                feature = data.get("feature")
                if feature: self._cmd_results[feature] = data.get("status")

        except Exception: pass

    def list_sticks(self, logger=None) -> list:
        self._stick_list = []
        self._response_event.clear()
        self._client.publish("solar/bridge/tx", json.dumps({"type": "LIST_STICKS"}))
        return self._stick_list if self._response_event.wait(timeout=self.timeout) else []

    def dump_adc(self, target_id: str, stick_uid: str, duration: float = 1.0, logger=None) -> list:
        tid_fmt = self._normalize_id(target_id)
        self._subscribe_sync([f"solar/mlpe/{tid_fmt}/adc"])
        
        self._adc_data[tid_fmt] = []
        self._cmd_results["DUMP_RAW_ADC"] = None
        
        self._client.publish(f"solar/feature/{stick_uid}/tx", json.dumps({
            "command": "DUMP_RAW_ADC", "args": {"target_id": tid_fmt, "duration": duration}
        }))

        end_time = time.time() + duration + 1.2 # Safety margin
        while time.time() < end_time:
            if self._cmd_results.get("DUMP_RAW_ADC") == "SUCCESS":
                if time.time() > (end_time - 1.0): break
            if self._cmd_results.get("DUMP_RAW_ADC") == "FAILED": break
            time.sleep(0.01)

        return self._adc_data.get(tid_fmt, [])

    def get_neighbors(self, stick_id: str, logger=None) -> list:
        res = self._run_command(stick_id, "0", "REQ_GET_NEIGHBORS", {}, logger=logger)
        return res.get("neighbors", []) if res else []

    def clear_neighbors(self, stick_id: str, logger=None) -> bool:
        self._response_event.clear()
        self._client.publish("solar/bridge/tx", json.dumps({"type": "CLEAR_NEIGHBORS", "stick_id": stick_id}))
        return self._clear_neighbors_results.get(stick_id, False) if self._response_event.wait(timeout=self.timeout) else False

    def get_device_info(self, target_id: str, stick_id: str, logger=None) -> Optional[dict]:
        return self._run_command(stick_id, target_id, "REQ_GET_INFO", {}, logger=logger)

    def req_shutdown(self, target_id: str, stick_uid: str, rsd1=True, rsd2=True, logger=None) -> Optional[dict]:
        args = {"target_id": target_id, "route": 2, "rsd1": rsd1, "rsd2": rsd2, "group_num1": 0xFFFFFFFF}
        return self._run_command(stick_uid, target_id, "REQ_SHUTDOWN", args, logger=logger)

    def _run_command(self, stick_uid: str, target_id: str, cmd_name: str, args: dict, logger=None) -> Optional[dict]:
        tid_norm = self._normalize_id(target_id)
        resp_name = cmd_name.replace("REQ_", "RESP_")
        
        self._subscribe_sync([f"solar/device/{stick_uid}/rx", f"solar/mlpe/{tid_norm}/rx"])
        self._cmd_results[cmd_name] = None
        self._responses.pop(resp_name, None)
        self._mlpe_data.pop(tid_norm, None)
        
        args["target_id"] = target_id
        if "route" not in args: args["route"] = 2 if target_id not in ["0", "0xFFFFFFFF"] else 1
        
        self._client.publish(f"solar/device/{stick_uid}/tx", json.dumps({"command": cmd_name, "args": args}))

        result_data = None
        end_time = time.time() + self.timeout
        while time.time() < end_time:
            if "GET" in cmd_name:
                if resp_name in self._responses:
                    result_data = self._responses[resp_name]
                    break
                if tid_norm in self._mlpe_data:
                    result_data = self._mlpe_data[tid_norm]
                    break
            if self._cmd_results.get(cmd_name) == "SUCCESS":
                if "GET" not in cmd_name:
                    result_data = {"status": "SUCCESS"}
                    break
            if self._cmd_results.get(cmd_name) and self._cmd_results.get(cmd_name) != "SUCCESS": break
            time.sleep(0.05)
        
        return result_data
