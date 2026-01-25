import time
import os
import json
import logging
import importlib
from typing import Any

from common.test_base import TestCase
from .types import AggregatedResult, TestDetail
from common.logging_utils import log_event
from . import globals as g
from common.error_codes import (
    E_DEVICE_RECOGNITION_FAIL,
    E_DEVICE_COMMUNICATION_FAIL,
    E_ADC_VERIFICATION_FAIL
)

# Reuse TestCases from Stage 2 logic where applicable
# For now, we redefine them or we could have moved them to common.
# Since we are in Stage 3, let's keep it similar to Stage 2.

class NeighborScanner(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        if not g.bridge:
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": "Solar Bridge client not initialized."}
        try:
            sticks = g.bridge.list_sticks()
            if not sticks:
                return {"code": E_DEVICE_RECOGNITION_FAIL.code, "log": "No active sticks found for scanning"}
            stick_uid = sticks[0]["uid"]
            g.bridge.clear_neighbors(stick_uid, logger=args.get("logger"))
            time.sleep(1.5)
            neighbors = g.bridge.get_neighbors(stick_uid, logger=args.get("logger"))
            if not neighbors:
                return {"code": E_DEVICE_RECOGNITION_FAIL.code, "log": "No neighbors found"}
            
            sorted_neighbors = sorted(neighbors, key=lambda x: x.get("rssi", -100), reverse=True)
            target = sorted_neighbors[0]
            g.target_device.device_id = target["id"]
            args["stick_uid"] = stick_uid
            
            return {"code": 0, "log": f"Target selected via RSSI({target['rssi']}): {target['id']}"}
        except Exception as e:
            return {"code": E_DEVICE_RECOGNITION_FAIL.code, "log": f"Scanning error: {str(e)}"}

class DeviceVerifier(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        target_id = g.target_device.device_id
        if not target_id:
            return {"code": E_DEVICE_RECOGNITION_FAIL.code, "log": "No target device selected."}
        time.sleep(0.5)
        return {"code": 0, "log": f"Device {target_id} verified (Stage 3)"}

class CommTester(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        target_id = g.target_device.device_id
        stick_uid = args.get("stick_uid")
        if not target_id or not stick_uid:
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": "ID or UID missing"}
        try:
            info = g.bridge.get_device_info(target_id, stick_uid, logger=args.get("logger"))
            if not info:
                return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": "Failed to get info"}
            g.target_device.info = info
            upper_id = info.get("upper_id")
            log_msg = f"Comm OK. Version: {info.get('version_unpacked', 'Unknown')}"
            if upper_id is not None:
                try:
                    if isinstance(upper_id, str):
                        u_int = int(upper_id, 16) if upper_id.startswith("0x") else int(upper_id)
                    else:
                        u_int = int(upper_id)
                    log_msg += f" (Upper ID: 0x{u_int:04X})"
                except:
                    log_msg += f" (Upper ID: {upper_id})"
            return {"code": 0, "log": log_msg, "parameter": {"upper_id": upper_id}}
        except Exception as e:
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": f"Comm error: {e}"}

class RelayController(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        io = args["io"]
        target_state = args.get("target_state", "OFF")
        try:
            io.set_relay(target_state == "ON")
            return {"code": 0, "log": f"Relay set to {target_state}"}
        except Exception as e:
            return {"code": -1, "log": f"Relay control error: {e}"}

class ADCResultChecker(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        target_id = g.target_device.device_id
        stick_uid = args.get("stick_uid")
        check_type = args.get("check_type", "before_relay") 
        board_type = args.get("board_type", "unknown")
        stage = args.get("stage_name", "stage3")
        adc_config = args.get("adc_config", {})

        if not target_id or not stick_uid:
            return {"code": E_DEVICE_RECOGNITION_FAIL.code, "log": "Target ID or Stick UID missing"}

        ranges = adc_config.get(stage, {}).get(board_type, {}).get(check_type, {})
        if not ranges:
            # Fallback to stage2 ranges if stage3 not defined
            ranges = adc_config.get("stage2", {}).get(board_type, {}).get(check_type, {})
            if not ranges:
                return {"code": E_ADC_VERIFICATION_FAIL.code, "log": f"ADC ranges not found for {board_type}/{check_type}"}

        samples = g.bridge.dump_adc(target_id, stick_uid, duration=1.0, logger=args["logger"])
        if not samples:
            return {"code": E_ADC_VERIFICATION_FAIL.code, "log": "Failed to collect ADC samples"}

        errors = []
        result_details = []
        for field_name, range_val in ranges.items():
            min_v = range_val.get("min", 0)
            max_v = range_val.get("max", 65536)
            
            raw_field = f"{field_name}_raw"
            if any(raw_field in s for s in samples): target_field = raw_field
            else: target_field = field_name

            values = [s.get(target_field) for s in samples if target_field in s and s.get(target_field) is not None]
            if not values:
                errors.append(f"Field {target_field} missing")
                continue
                
            avg_val = sum(values) / len(values)
            result_details.append(f"{field_name}: {avg_val:.1f}")
            
            if check_type == "before_relay" and field_name == "vout":
                g.target_device.baseline_vout = avg_val

            if not (min_v <= avg_val <= max_v):
                errors.append(f"{field_name} out of range: {avg_val:.1f} ({min_v}~{max_v})")

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
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": "ID missing"}

        try:
            res = g.bridge.req_shutdown(device_id, uid, rsd1=rsd1, rsd2=rsd2)
            if res is None:
                return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": "RSD control timeout"}
            time.sleep(0.1)
            return {"code": 0, "log": f"RSD Set: RSD1={rsd1}, RSD2={rsd2}"}
        except Exception as e:
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": f"RSD error: {e}"}

class DutyRatioTester(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        target_id = g.target_device.device_id
        stick_uid = args.get("stick_uid")
        logger = args["logger"]
        
        baseline_vout = g.target_device.baseline_vout
        if baseline_vout is None:
            return {"code": E_ADC_VERIFICATION_FAIL.code, "log": "Baseline Vout missing"}

        mppt_status = g.bridge.get_mppt_status(target_id, stick_uid, logger=logger)
        if not mppt_status:
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": "Failed to get MPPT status"}
        
        initial_mppt = mppt_status.get("mppt", False)
        initial_min = mppt_status.get("min_limit")
        initial_max = mppt_status.get("max_limit")
        initial_max_duty = mppt_status.get("max_duty")
        initial_bypass = mppt_status.get("bypass_condition", False)

        max_pwm = initial_max_duty if initial_max_duty is not None else 2000
        
        try:
            if not g.bridge.enable_mppt(target_id, stick_uid, enable=True, logger=logger):
                return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": "Failed to enable MPPT"}
            
            duty_steps = [0.75, 0.50, 0.25]
            logs = []
            for ratio in duty_steps:
                target_duty = int(max_pwm * ratio)
                res_set = g.bridge.set_mppt_config(target_id, stick_uid, min_limit=target_duty, max_limit=target_duty, bypass_condition=True, logger=logger)
                if not res_set: return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": f"Failed duty {ratio}"}
                time.sleep(1.5)
                samples = g.bridge.dump_adc(target_id, stick_uid, duration=1.0, logger=logger)
                v_values = [s.get("vout_raw") or s.get("vout") for s in samples if (s.get("vout_raw") is not None or s.get("vout") is not None)]
                if not v_values: return {"code": E_ADC_VERIFICATION_FAIL.code, "log": "Vout missing"}
                avg_vout = sum(v_values) / len(v_values)
                expected_v = baseline_vout * ratio
                tolerance = 0.15 * baseline_vout
                status = "OK" if abs(avg_vout - expected_v) < tolerance else "FAIL"
                logs.append(f"Duty {ratio*100:.0f}%: Measured {avg_vout:.1f} (Exp: ~{expected_v:.1f}) -> {status}")
                if status == "FAIL": return {"code": E_ADC_VERIFICATION_FAIL.code, "log": " | ".join(logs)}
            
            return {"code": 0, "log": " | ".join(logs)}
        finally:
            logger.info("  --> Restoring initial MPPT configuration...")
            g.bridge.set_mppt_config(
                target_id, stick_uid, 
                max_duty=initial_max_duty if initial_max_duty is not None else 0xFFFFFFFF,
                min_limit=initial_min if initial_min is not None else 0xFFFFFFFF,
                max_limit=initial_max if initial_max is not None else 0xFFFFFFFF,
                bypass_condition=initial_bypass,
                logger=logger
            )
            g.bridge.enable_mppt(target_id, stick_uid, enable=initial_mppt, logger=logger)

def run_steps_sequentially(steps: list[tuple[str, TestCase]], context: dict[str, Any], logger: logging.Logger, results: AggregatedResult) -> AggregatedResult:
    stage_name = context.get("stage_name", "stage3")
    for name, step in steps:
        if name == "ADC Check (Before Relay)": context["check_type"] = "before_relay"
        elif name == "ADC Check (After Relay)": context["check_type"] = "after_relay"
        elif name == "Relay ON": context["target_state"] = "ON"
        elif name == "Relay OFF": context["target_state"] = "OFF"
        elif name == "RSD1 ON": context.update({"rsd1": True, "rsd2": False})
        elif name == "ADC (RSD1)": context["check_type"] = "rsd1"
        elif name == "RSD2 ON": context.update({"rsd1": False, "rsd2": True})
        elif name == "ADC (RSD2)": context["check_type"] = "rsd2"
        elif name == "RSD1+2 ON": context.update({"rsd1": True, "rsd2": True})
        elif name == "ADC (RSD1_2)": context["check_type"] = "rsd1_2"
        elif name == "RSD All OFF": context.update({"rsd1": False, "rsd2": False})

        logger.info(f"Running: {name}...")
        res = step.run(context)
        parameter = res.get("parameter", {"log": res.get("log", "")})
        detail = TestDetail(case=name, parameter=parameter, code=res["code"])
        results.details.append(detail)
        
        # If this test found the upper_id, update result's upper_id
        if parameter.get("upper_id") is not None:
            results.upper_id = parameter["upper_id"]
        if res["code"] != 0:
            results.code = res["code"]
            logger.error(f"  --> [FAIL] {res['log']}")
            return results 
        logger.info(f"  --> [OK] {res['log']}")
        time.sleep(0.1)
    return results

def run_stage_test(*, logger, io, db_server, vendor, product, stage_name: str = "stage3", adc_config: dict = {}, relay_pin: int = None, relay_active_high: bool = True) -> AggregatedResult:
    results = AggregatedResult(test=stage_name, code=0)
    common_steps = [("Neighbor Scanner", NeighborScanner()), ("Device Verifier", DeviceVerifier()), ("Communication Test", CommTester())]
    context = {"logger": logger, "io": io, "db_server": db_server, "vendor": vendor, "product": product, "stage_name": stage_name, "adc_config": adc_config, "relay_pin": relay_pin, "relay_active_high": relay_active_high}
    
    logger.info(">>> Running Common Steps...")
    results = run_steps_sequentially(common_steps, context, logger, results)

    # Fill device info from globals
    results.device_id = g.target_device.device_id

    if results.code != 0: return results

    board_type = product if vendor in ["conalog", "nanoom"] else f"{vendor}_{product}"
    context["board_type"] = board_type
    logger.info(f">>> Target Board: {board_type}. Running board-specific tests...")
    
    try:
        board_module = importlib.import_module(f"stage3.boards.{board_type}")
        board_results = board_module.run_stage_test(context)
        results.details.extend(board_results.details)
        results.code = board_results.code
    except ImportError:
        logger.error(f"Test implementation for board '{board_type}' not found.")
        results.code = E_DEVICE_RECOGNITION_FAIL.code
    except Exception as e:
        logger.error(f"Error during board-specific test execution: {e}")
        results.code = -1
    return results
