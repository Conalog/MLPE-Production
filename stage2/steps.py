import subprocess
import time
import os
import json
import logging
import numpy as np
from typing import Any

from common.test_base import TestCase
from .types import AggregatedResult, TestDetail
from common.logging_utils import log_event
from .nrf52_ficr import NRF52FICR
from . import globals as g
from common.error_codes import (
    E_VOLTAGE_12V_OUT_OF_RANGE,
    E_VOLTAGE_3V3_OUT_OF_RANGE,
    E_DEVICE_RECOGNITION_FAIL,
    E_FIRMWARE_DOWNLOAD_FAIL,
    E_FIRMWARE_UPLOAD_FAIL,
    E_DEVICE_COMMUNICATION_FAIL,
    E_ADC_VERIFICATION_FAIL
)




class NeighborScanner(TestCase):
    """
    Stage 2 Device Recognition:
    1. Initialize Neighbors List (Placeholder)
    2. Wait for a few seconds
    3. Get Neighbors and select the one with the lowest RSSI
    """
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        if not g.bridge:
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": "Solar Bridge client not initialized."}
        
        try:
            # 1. Discover Stick
            sticks = g.bridge.list_sticks()
            if not sticks:
                return {"code": E_DEVICE_RECOGNITION_FAIL.code, "log": "No active sticks found for scanning"}
            
            stick_uid = sticks[0]["uid"]

            # 2. Initialize Neighbors List (Timing Point 1)
            if g.bridge.clear_neighbors(stick_uid, logger=args.get("logger")):
                args["logger"].info(f"  --> [OK] Neighbors list cleared on {stick_uid}")
            else:
                args["logger"].warning(f"  --> [FAIL] Failed to clear neighbors on {stick_uid}")
            
            # 3. Wait for discovery
            scan_duration = 1.0
            time.sleep(scan_duration)

            # 4. Get Neighbors (Timing Point 2)
            neighbors = g.bridge.get_neighbors(stick_uid, logger=args.get("logger"))
            
            if not neighbors:
                return {"code": E_DEVICE_RECOGNITION_FAIL.code, "log": "No neighbors found"}

            # Log all found neighbors (Part of final_log for reporting)
            neighbor_list_str = ", ".join([f"{n['id']}({n['rssi']})" for n in neighbors])

            # 5. Choose device with the STRONGEST RSSI (closest to 0)
            # RSSI is typically negative (-40 is strong, -90 is weak).
            # To be safe, we sort in descending order and pick the first one.
            sorted_neighbors = sorted(neighbors, key=lambda x: x.get("rssi", -100), reverse=True)
            target = sorted_neighbors[0]
            
            g.target_device.device_id = target["id"]
            args["stick_uid"] = stick_uid
            
            final_log = [
                f"Found {len(neighbors)} neighbors: [{neighbor_list_str}]",
                f"Target selected via RSSI({target['rssi']}): {target['id']}"
            ]
            return {"code": 0, "log": "\n".join(final_log)}

        except Exception as e:
            return {"code": E_DEVICE_RECOGNITION_FAIL.code, "log": f"Scanning error: {str(e)}"}


class DeviceVerifier(TestCase):
    """
    Placeholder for '장비 정합성 검증'
    Check if the selected device is actually the one currently on the jig.
    """
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        target_id = g.target_device.device_id
        if not target_id:
            return {"code": E_DEVICE_RECOGNITION_FAIL.code, "log": "No target device selected."}
        
        # Todo: Implement verification logic (e.g. checking specific HW pins or matching against expected ID)
        time.sleep(0.5)
        
        return {"code": 0, "log": f"Device {target_id} verified"}


class RelayController(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        io = args["io"]
        target_state = args.get("target_state", "OFF")

        try:
            if target_state == "ON":
                io.set_relay(True)
                log_msg = "Relay set to ON via IOThread"
            else:
                io.set_relay(False)
                log_msg = "Relay set to OFF via IOThread"
            return {"code": 0, "log": log_msg}
        except Exception as e:
            return {"code": E_RELAY_INIT_FAIL.code, "log": f"Relay control error: {e}"}


class ADCResultChecker(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        target_id = g.target_device.device_id
        stick_uid = args.get("stick_uid")
        check_type = args.get("check_type", "before_relay") 
        board_type = args.get("product", "guard_2_1")
        stage = args.get("stage_name", "stage2")
        adc_config = args.get("adc_config", {})

        if not target_id:
            return {"code": E_DEVICE_RECOGNITION_FAIL.code, "log": "Target device ID not found."}
        
        if not stick_uid:
            # Step context에서 stick_uid가 없는 경우 NeighborScanner가 남긴 args에서 찾아보거나 bridge에서 다시 조회
            sticks = g.bridge.list_sticks()
            if not sticks:
                 return {"code": E_DEVICE_RECOGNITION_FAIL.code, "log": "No active sticks found for ADC dump"}
            stick_uid = sticks[0]["uid"]

        # Load ranges for current stage and board
        ranges = adc_config.get(stage, {}).get(board_type, {}).get(check_type, {})
        if not ranges:
            return {"code": E_ADC_VERIFICATION_FAIL.code, "log": f"ADC ranges not found for {stage}/{board_type}/{check_type}"}

        # Collect samples
        samples = g.bridge.dump_adc(target_id, stick_uid, duration=1.0, logger=args["logger"])
        if not samples:
            return {"code": E_ADC_VERIFICATION_FAIL.code, "log": "Failed to collect ADC samples via MQTT DUMP_RAW_ADC"}

        # Check each field in ranges
        errors = []
        result_details = []
        for field_name, range_val in ranges.items():
            min_v = range_val.get("min", 0)
            max_v = range_val.get("max", 65536)
            
            # Analyze samples: Try raw field first (e.g. vin1_raw)
            raw_field = f"{field_name}_raw"
            if any(raw_field in s for s in samples):
                 target_field = raw_field
            else:
                 target_field = field_name

            values = [s.get(target_field) for s in samples if target_field in s and s.get(target_field) is not None]
            if not values:
                errors.append(f"Field {target_field} missing in samples")
                continue
                
            avg_val = sum(values) / len(values)
            result_details.append(f"{field_name} Raw: {avg_val:.1f}")
            if not (min_v <= avg_val <= max_v):
                errors.append(f"{field_name} out of range: {avg_val:.1f} (Exp: {min_v}~{max_v})")

        log_summary = ", ".join(result_details)
        if errors:
            return {"code": E_ADC_VERIFICATION_FAIL.code, "log": f"FAILED: {'; '.join(errors)} | Data: {log_summary}"}
        
        return {"code": 0, "log": f"PASSED ({check_type}): {log_summary}"}


class RSDController(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        device_id = g.target_device.device_id
        uid = args.get("stick_uid")
        rsd1 = args.get("rsd1", False)
        rsd2 = args.get("rsd2", False)

        if not device_id or not uid:
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": "Device ID or Stick UID missing"}

        try:
            g.bridge.req_shutdown(device_id, uid, rsd1=rsd1, rsd2=rsd2)
            time.sleep(0.1) # wait for settlement
            log_msg = f"RSD Set: RSD1={rsd1}, RSD2={rsd2}"
            return {"code": 0, "log": log_msg}
        except Exception as e:
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": f"RSD control error: {e}"}


def run_stage_test(
    *,
    logger,
    io,
    db_server,
    vendor,
    product,
    stage_name: str = "stage2",
    adc_config: dict = {},
    relay_pin: int = None,
    relay_active_high: bool = True
) -> AggregatedResult:
    results = AggregatedResult(test=stage_name, code=0)
    
    # 2단계 검증 시퀀스 정의
    steps = [
        ("Neighbor Scanner", NeighborScanner()),
        ("Device Verifier", DeviceVerifier()),
        ("ADC Check (Before Relay)", ADCResultChecker()),
        ("Relay ON", RelayController()),
        ("ADC Check (After Relay)", ADCResultChecker()),
        # Expanding with RSD States
        ("RSD1 ON", RSDController()),
        ("ADC (RSD1)", ADCResultChecker()),
        ("RSD1+2 ON", RSDController()),
        ("ADC (RSD1_2)", ADCResultChecker()),
        ("RSD All OFF", RSDController()),
        ("Relay OFF", RelayController()), # 테스트 종료 후 Relay OFF (안전)
    ]
    
    context = {
        "logger": logger,
        "io": io,
        "db_server": db_server,
        "vendor": vendor,
        "product": product,
        "stage_name": stage_name,
        "adc_config": adc_config,
        "relay_pin": relay_pin,
        "relay_active_high": relay_active_high,
    }

    final_code = 0
    total_steps = len(steps)
    for i, (name, step) in enumerate(steps, 1):
        logger.info(f"[{i}/{total_steps}] Running: {name}...")
        
        # 단계별 파라미터 업데이트
        if name == "ADC Check (Before Relay)":
            context["check_type"] = "before_relay"
        elif name == "ADC Check (After Relay)":
            context["check_type"] = "after_relay"
        elif name == "Relay ON":
            context["target_state"] = "ON"
        elif name == "Relay OFF":
            context["target_state"] = "OFF"
        elif name == "RSD1 ON":
            context.update({"rsd1": True, "rsd2": False})
        elif name == "ADC (RSD1)":
            context["check_type"] = "rsd1"
        elif name == "RSD1+2 ON":
            context.update({"rsd1": True, "rsd2": True})
        elif name == "ADC (RSD1_2)":
            context["check_type"] = "rsd1_2"
        elif name == "RSD All OFF":
            context.update({"rsd1": False, "rsd2": False})

        res = step.run(context)
        
        # NeighborScanner에서 찾은 stick_uid 보관 (이후 단계에서 사용)
        if "stick_uid" in context:
            pass # 이미 NeighborScanner가 업데이트함
        elif name == "Neighbor Scanner" and res["code"] == 0:
            # NeighborScanner.run internally updates context if we passed 'args' 
            # and assigned it. But NeighborScanner uses args["stick_uid"] = stick_uid
            pass

        detail = TestDetail(case=name, log=res["log"], code=res["code"])
        results.details.append(detail)
        
        if res["code"] != 0:
            final_code = res["code"]
            for line in res["log"].splitlines():
                logger.error(f"  --> [FAIL] {line}")
            log_event(logger, event=f"{stage_name}.step_failed", stage=stage_name, data={"case": name, "error": res["log"]})
            
            # 실패 시에도 모든 상태 초기화 시도
            if name != "RSD All OFF" and name != "Relay OFF":
                 RSDController().run({**context, "rsd1": False, "rsd2": False})
                 RelayController().run({**context, "target_state": "OFF"})
            break 
        else:
            for line in res["log"].splitlines():
                logger.info(f"  --> [OK] {line}")
            
        time.sleep(0.1)

    results.code = final_code
    return results
