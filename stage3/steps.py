import subprocess
import time
import os
import json
import logging
import numpy as np
import importlib
from typing import Any

from common.test_base import TestCase
from .types import AggregatedResult, TestDetail
from common.logging_utils import log_event
from .nrf52_ficr import NRF52FICR
from . import globals as g
from common.label_utils import LabelGenerator, load_label_profiles, generate_zpl_from_png, send_zpl_to_printer
from common.error_codes import (
    E_RELAY_INIT_FAIL,
    E_VOLTAGE_12V_OUT_OF_RANGE,
    E_VOLTAGE_3V3_OUT_OF_RANGE,
    E_DEVICE_RECOGNITION_FAIL,
    E_NEIGHBOR_NOT_FOUND,
    E_FIRMWARE_DOWNLOAD_FAIL,
    E_FIRMWARE_UPLOAD_FAIL,
    E_DEVICE_COMMUNICATION_FAIL,
    E_ADC_VERIFICATION_FAIL,
    E_DUTY_RATIO_VERIFICATION_FAIL,
    E_MESH_CONFIG_FAIL,
    E_FINAL_MESH_CONFIG_FAIL,
    E_LABEL_PRINT_FAIL
)

# Vendor/Product ID Mapping (matches solar-bridge/internal/models/metadata.go)
VENDOR_MAP = {
    "stick": 0,
    "conalog": 1,
    "nanoom": 2,
}

PRODUCT_MAP = {
    "stick": 0,
    "guard_1_1": 1,
    "guard_2_1": 2,
    "booster_1_1": 3,
    "booster_2_1": 4,
}




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
                return {"code": E_NEIGHBOR_NOT_FOUND.code, "log": "No active sticks found for scanning"}
            
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
                return {"code": E_NEIGHBOR_NOT_FOUND.code, "log": "No neighbors found"}

            # Log all found neighbors
            def get_ver(n):
                v = n.get("version", "v0.0.0")
                return v

            neighbor_list_str = ", ".join([f"{n['id']}({n['rssi']}, v:{get_ver(n)})" for n in neighbors])
            args["logger"].debug(f"Found {len(neighbors)} neighbors: [{neighbor_list_str}]")

            # 5. Filter by Vendor and Product ID from Config
            expected_vendor = args.get("vendor", "conalog").lower()
            expected_product = args.get("product", "unknown").lower()
            
            # Map names to IDs
            target_vid = VENDOR_MAP.get(expected_vendor)
            target_pid = PRODUCT_MAP.get(expected_product)
            
            if target_vid is None or target_pid is None:
                args["logger"].warning(f"Unknown vendor/product in config: {expected_vendor}/{expected_product}. ID filtering bypassed.")
                matching_neighbors = neighbors
            else:
                matching_neighbors = []
                for n in neighbors:
                    # Filter by string match (case-insensitive)
                    # Bridge returns "Conalog", "Guard_2_1" etc via models.GetSolarVendorName
                    vid_name = n.get("vid", "unknown").lower()
                    pid_name = n.get("pid", "unknown").lower()
                    
                    if vid_name == expected_vendor and pid_name == expected_product:
                        matching_neighbors.append(n)
                
                if not matching_neighbors:
                    log_err = f"No devices found matching {expected_vendor}/{expected_product}. Found: {neighbor_list_str}"
                    return {"code": E_NEIGHBOR_NOT_FOUND.code, "log": log_err}

            # 6. Choose device with the STRONGEST RSSI from matches
            sorted_matches = sorted(matching_neighbors, key=lambda x: x.get("rssi", -100), reverse=True)
            target = sorted_matches[0]
            
            g.target_device.device_id = target["id"]
            args["stick_uid"] = stick_uid
            
            final_log = [
                f"Found {len(neighbors)} neighbors total.",
                f"Filtered {len(matching_neighbors)} matches for {expected_vendor}/{expected_product}.",
                f"Target selected via RSSI({target['rssi']}): {target['id']}"
            ]
            log_summary = "\n".join(final_log)
            return {
                "code": 0, 
                "log": log_summary,
                "parameter": {
                    "log": log_summary,
                    "neighbors": neighbors,
                    "matches": matching_neighbors,
                    "selected_id": target["id"]
                }
            }

        except Exception as e:
            return {"code": E_DEVICE_RECOGNITION_FAIL.code, "log": f"Scanning error: {str(e)}"}


class CommTester(TestCase):
    """
    Check communication with the target device and get info (id_high).
    """
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        target_id = g.target_device.device_id
        stick_uid = args.get("stick_uid")
        if not target_id or not stick_uid:
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": "Device ID or Stick UID missing"}
        
        try:
            info = g.bridge.get_device_info(target_id, stick_uid, logger=args.get("logger"))
            if not info:
                return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": f"Failed to get info from {target_id}"}
            
            g.target_device.info = info
            upper_id = info.get("upper_id")
            g.target_device.upper_id = upper_id
            
            log_msg = f"Communication OK. Version: {info.get('version_unpacked', 'Unknown')}"
            if upper_id is not None:
                try:
                    if isinstance(upper_id, str):
                        u_int = int(upper_id, 16) if upper_id.startswith("0x") else int(upper_id)
                    else:
                        u_int = int(upper_id)
                    log_msg += f" (Upper ID: 0x{u_int:04X})"
                except (ValueError, TypeError):
                    log_msg += f" (Upper ID: {upper_id})"
            
            parameter = {
                "log": log_msg,
                "version": info.get("version_unpacked", "Unknown"),
                "uptime": info.get("uptime", 0),
                "upper_id": upper_id
            }
            return {"code": 0, "log": log_msg, "parameter": parameter}
        except Exception as e:
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": f"Communication error: {e}"}


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
            return {
                "code": 0, 
                "log": log_msg, 
                "parameter": {
                    "log": log_msg, 
                    "target_state": target_state
                }
            }
        except Exception as e:
            return {"code": E_RELAY_INIT_FAIL.code, "log": f"Relay control error: {e}"}


class ADCResultChecker(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        target_id = g.target_device.device_id
        stick_uid = args.get("stick_uid")
        check_type = args.get("check_type", "before_relay") 
        board_type = args.get("board_type", "guard_2_1")
        stage = args.get("stage_name", "stage3")
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
            
            # Save baseline Vout for DutyRatio test if applicable
            if check_type == "before_relay" and field_name == "vout":
                g.target_device.baseline_vout = avg_val
                args["logger"].debug(f"Saved baseline_vout: {avg_val:.1f}")

            if not (min_v <= avg_val <= max_v):
                errors.append(f"{field_name} out of range: {avg_val:.1f} (Exp: {min_v}~{max_v})")

        log_summary = ", ".join(result_details)
        params = {"log": log_summary}
        for field_name, range_val in ranges.items():
            target_field = f"{field_name}_raw" if any(f"{field_name}_raw" in s for s in samples) else field_name
            vals = [s.get(target_field) for s in samples if target_field in s and s.get(target_field) is not None]
            if vals:
                params[field_name] = sum(vals) / len(vals)
            else:
                params[field_name] = 0.0

        if errors:
            res_log_fail = f"FAILED ({check_type}): " + "; ".join(errors) + f" | Data: {log_summary}"
            params["log"] = res_log_fail
            return {"code": E_ADC_VERIFICATION_FAIL.code, "log": res_log_fail, "parameter": params}
        
        return {"code": 0, "log": f"PASSED ({check_type}): {log_summary}", "parameter": params}


class RSDController(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        device_id = g.target_device.device_id
        uid = args.get("stick_uid")
        rsd1 = args.get("rsd1", False)
        rsd2 = args.get("rsd2", False)

        if not device_id or not uid:
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": "Device ID or Stick UID missing"}

        try:
            res = g.bridge.req_shutdown(device_id, uid, rsd1=rsd1, rsd2=rsd2)
            if res is None:
                return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": f"RSD control timeout: No response from {device_id}"}
            
            time.sleep(0.1) # wait for settlement
            log_msg = f"RSD Set: RSD1={rsd1}, RSD2={rsd2}"
            return {
                "code": 0, 
                "log": log_msg,
                "parameter": {
                    "log": log_msg,
                    "RSD1": rsd1,
                    "RSD2": rsd2
                }
            }
        except Exception as e:
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": f"RSD control error: {e}"}


class DutyRatioTester(TestCase):
    """
    Booster Duty control and output voltage verification.
    Verifies that Vout changes proportionally to PWM Duty (25%, 50%, 75%).
    """
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        target_id = g.target_device.device_id
        stick_uid = args.get("stick_uid")
        logger = args["logger"]
        
        if not target_id or not stick_uid:
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": "Device ID or Stick UID missing"}

        # 1. Initial Vout (baseline)
        baseline_vout = g.target_device.baseline_vout
        if baseline_vout is None:
            return {"code": E_ADC_VERIFICATION_FAIL.code, "log": "Baseline Vout not found. Ensure ADC Check (Before Relay) ran first."}
        
        logger.info(f"  --> Baseline Vout: {baseline_vout:.1f}")

        # 2. Get Initial MPPT Status (Backup)
        mppt_status = g.bridge.get_mppt_status(target_id, stick_uid, logger=logger)
        if not mppt_status:
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": "Failed to get MPPT status"}
        
        initial_mppt = mppt_status.get("mppt", False)
        initial_min = mppt_status.get("min_limit")
        initial_max = mppt_status.get("max_limit")
        initial_max_duty = mppt_status.get("max_duty")
        initial_bypass = mppt_status.get("bypass_condition", False)
        
        if initial_max_duty is None:
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": "Failed to detect Max Duty from MPPT status. Check device connection."}
        max_pwm = initial_max_duty
        logger.info(f"  --> Detected Max Duty: {max_pwm}")

        try:
            # 3. MPPT Enable
            if not g.bridge.enable_mppt(target_id, stick_uid, enable=True, logger=logger):
                return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": "Failed to enable MPPT"}
            
            logger.info("  --> MPPT Enabled. Starting Duty Sequence...")

            # 4-9. Set Duty and Check ADC
            duty_steps = [0.75, 0.50, 0.25]
            logs = []
            duty_results = []
            
            for ratio in duty_steps:
                target_duty = int(max_pwm * ratio)
                logger.info(f"  --> Setting Duty to {ratio*100:.0f}% ({target_duty})...")
                
                # Set fixed duty by setting min=max=target_duty
                res_set = g.bridge.set_mppt_config(
                    target_id, stick_uid, 
                    min_limit=target_duty, 
                    max_limit=target_duty, 
                    bypass_condition=True,
                    logger=logger
                )
                if not res_set:
                    return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": f"Failed to set duty to {ratio*100:.0f}%"}
                
                time.sleep(1.5) # Wait for stability
                
                # ADC Check
                samples = g.bridge.dump_adc(target_id, stick_uid, duration=1.0, logger=logger)
                if not samples:
                    return {"code": E_ADC_VERIFICATION_FAIL.code, "log": f"Failed to collect ADC samples for {ratio*100:.0f}% duty"}
                
                # Calculate average vout
                v_values = [s.get("vout_raw") or s.get("vout") for s in samples if (s.get("vout_raw") is not None or s.get("vout") is not None)]
                if not v_values:
                    return {"code": E_ADC_VERIFICATION_FAIL.code, "log": f"Vout field missing in samples for {ratio*100:.0f}% duty"}
                
                avg_vout = sum(v_values) / len(v_values)
                
                # Verification
                expected_v = baseline_vout * ratio
                tolerance = 0.15 * baseline_vout # 15% tolerance
                
                status = "OK" if abs(avg_vout - expected_v) < tolerance else "FAIL"
                step_log = f"Duty {ratio*100:.0f}%: Measured {avg_vout:.1f} (Exp: ~{expected_v:.1f}) -> {status}"
                logs.append(step_log)
                duty_results.append({
                    "ratio": ratio,
                    "target_duty": target_duty,
                    "measured_vout": avg_vout,
                    "expected_vout": expected_v,
                    "status": status
                })
                
                if status == "FAIL":
                    log_summary = " | ".join(logs)
                    return {
                        "code": E_DUTY_RATIO_VERIFICATION_FAIL.code, 
                        "log": log_summary,
                        "parameter": {
                            "log": log_summary,
                            "baseline_vout": baseline_vout,
                            "max_pwm": max_pwm,
                            "steps": duty_results
                        }
                    }

            log_summary = " | ".join(logs)
            return {
                "code": 0, 
                "log": log_summary,
                "parameter": {
                    "log": log_summary,
                    "baseline_vout": baseline_vout,
                    "max_pwm": max_pwm,
                    "steps": duty_results
                }
            }

        finally:
            logger.info("  --> Restoring initial MPPT configuration...")
            # Restore settings (use original values or do-not-change 0xFFFFFFFF if missing)
            g.bridge.set_mppt_config(
                target_id, stick_uid, 
                max_duty=initial_max_duty if initial_max_duty is not None else 0xFFFFFFFF,
                min_limit=initial_min if initial_min is not None else 0xFFFFFFFF,
                max_limit=initial_max if initial_max is not None else 0xFFFFFFFF,
                bypass_condition=initial_bypass,
                logger=logger
            )
            g.bridge.enable_mppt(target_id, stick_uid, enable=initial_mppt, logger=logger)


class FinalMeshConfigurator(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        target_id = g.target_device.device_id
        stick_uid = args.get("stick_uid")

        if not target_id:
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": "Device ID (Target ID) not found."}
        if not stick_uid:
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": "Stick UID not found in context."}

        # Set final mesh config: ASP 10s (10000ms), TxPwr 4dBm
        resp = g.bridge.set_mesh_config(target_id, stick_uid, asp_interval=10000, tx_pwr=4, logger=args.get("logger"))
        if resp is None:
            return {"code": E_MESH_CONFIG_FAIL.code, "log": f"Final Mesh config timeout: No response from {target_id}"}
            
        # Verify response matches requested values
        rx_l1 = resp.get("l1", {})
        rx_l2 = resp.get("l2", {})
        
        # Support both snake_case (Go json tags) and camelCase
        rx_tx_pwr = rx_l1.get("tx_pwr") if rx_l1.get("tx_pwr") is not None else rx_l1.get("txPwr")
        rx_asp = rx_l2.get("asp_interval") if rx_l2.get("asp_interval") is not None else rx_l2.get("aspInterval")

        if rx_tx_pwr != 4 or rx_asp != 10000:
            def fmt_val(v): return "None" if v is None else v
            err_msg = f"Final Mesh config verification failed: Exp(ASP=10000ms, TxPwr=4dBm) != Rx(ASP={fmt_val(rx_asp)}ms, TxPwr={fmt_val(rx_tx_pwr)}dBm)"
            if rx_tx_pwr is None or rx_asp is None:
                err_msg += " (Some fields are missing in the response)"
            
            return {
                "code": E_FINAL_MESH_CONFIG_FAIL.code, 
                "log": err_msg,
                "parameter": {
                    "log": err_msg,
                    "expected": {"asp": 10000, "txPwr": 4},
                    "received": {"asp": rx_asp, "txPwr": rx_tx_pwr},
                    "full_response": resp
                }
            }

        log_msg = f"Final Mesh config verified (ASP: 10s, TxPwr: 4dBm) for {target_id}"
        return {
            "code": 0, 
            "log": log_msg,
            "parameter": {
                "log": log_msg,
                "l1": rx_l1,
                "l2": rx_l2,
                "l3": resp.get("l3", {})
            }
        }


class LabelPrinter(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        logger = args.get("logger", logging.getLogger(__name__))
        logger.info(f"LabelPrinter starting with args keys: {list(args.keys())}")
        
        target_id_lower = g.target_device.device_id
        vendor = args.get("vendor", "conalog").lower()
        
        label_cfg = args.get("label", {})
        logger.info(f"Extracted label_cfg: {label_cfg}")
        
        upper_id = getattr(g.target_device, 'upper_id', None)
        if upper_id is None and hasattr(g.target_device, 'info') and g.target_device.info:
            upper_id = g.target_device.info.get("upper_id")
            
        # Ensure both IDs are present
        if not target_id_lower:
            return {"code": E_LABEL_PRINT_FAIL.code, "log": "Lower Device ID (4-byte) missing for label printing."}
        if upper_id is None:
            return {"code": E_LABEL_PRINT_FAIL.code, "log": "Upper Device ID (2-byte) missing for label printing."}

        # Normalize IDs to 12-char hex (Upper 4 + Lower 8)
        lower_str = target_id_lower.replace("0x", "").replace("0X", "").zfill(8).upper()
        
        if isinstance(upper_id, str):
            u_int = int(upper_id, 16) if upper_id.startswith("0x") else int(upper_id)
        else:
            u_int = int(upper_id)
        upper_str = f"{u_int:04X}"
            
        unique_id_12 = (upper_str + lower_str).upper()
        
        # 1. Load Label Configuration from preset
        label_cfg = args.get("label", {})
        preset_name = label_cfg.get("preset")
        
        profiles = load_label_profiles()
        
        # Select profile based on preset_name, or fallback to vendor-based default
        if preset_name in profiles:
            profile_key = preset_name
        else:
            profile_key = f"{vendor}_standard_label" if f"{vendor}_standard_label" in profiles else "conalog_standard_label"
            
        profile = profiles.get(profile_key)
        
        if not profile:
            return {"code": E_LABEL_PRINT_FAIL.code, "log": f"Label profile for preset '{preset_name}' or vendor '{vendor}' not found."}

        # 2. Prepare Meta-data Dictionary for Rendering
        kc_no = label_cfg.get("kc_no")
        if not kc_no:
            return {"code": E_LABEL_PRINT_FAIL.code, "log": "KC Number ('kc_no') missing in label configuration."}
        
        kc_lines = kc_no.split("\n")
        
        # Split kc_no into lines if it's long and doesn't have a newline
        if "\n" not in kc_no and len(kc_no) > 12:
            # Try to find a hyphen to split around the middle (e.g. index 8 to 14)
            split_idx = -1
            for i in range(min(len(kc_no)-1, 14), 7, -1):
                if kc_no[i] == '-':
                    split_idx = i
                    break
            
            if split_idx != -1:
                kc_lines = [kc_no[:split_idx], kc_no[split_idx+1:]]
            else:
                kc_lines = [kc_no[:12], kc_no[12:]]
        
        label_data = {
            "device_id": unique_id_12,
            "company": label_cfg.get("authenticator"),
            "model": label_cfg.get("model"),
            "yyyymm": time.strftime("%Y-%m"),
            "kc_no": kc_no,
            "kc_no_line1": kc_lines[0] if len(kc_lines) > 0 else "",
            "kc_no_line2": kc_lines[1] if len(kc_lines) > 1 else "",
            "nation": "Korea",
            "qr_text": f"https://v.conalog.com/d/{unique_id_12}",
        }
        # Merge all config keys to support dynamic fields like jp_no
        label_data.update(label_cfg)

        gen = LabelGenerator()
        try:
            # Step 1: Build Image (Data-Driven Layout)
            png_path = gen.build_label_png(label_data, "/tmp/label.png", profile=profile)
            
            # Step 3: Convert Image to ZPL (Step 2 is handled inside build_label_png)
            zpl = generate_zpl_from_png(png_path, profile=profile)
            
            # Step 4: Send to Printer
            printer_name = args.get("printer_name", "ZD421")
            send_zpl_to_printer(zpl, printer_name=printer_name)
            
            log_msg = f"Label printed for {unique_id_12} using '{profile_key}' preset on {printer_name}."
            return {
                "code": 0, 
                "log": log_msg,
                "parameter": {
                    "log": log_msg,
                    "device_id_12": unique_id_12,
                    "preset_used": profile_key,
                    "label_path": png_path
                }
            }
        except Exception as e:
            return {"code": E_LABEL_PRINT_FAIL.code, "log": f"Label Printing Sequence Error: {str(e)}"}



def run_steps_sequentially(
    steps: list[tuple[str, TestCase]],
    context: dict[str, Any],
    logger: logging.Logger,
    results: AggregatedResult
) -> AggregatedResult:
    total_steps = len(steps)
    stage_name = context.get("stage_name", "stage3")
    
    for i, (name, step) in enumerate(steps, 1):
        # Step specific overrides
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
        elif name == "RSD2 ON":
            context.update({"rsd1": False, "rsd2": True})
        elif name == "ADC (RSD2)":
            context["check_type"] = "rsd2"
        elif name == "RSD1+2 ON":
            context.update({"rsd1": True, "rsd2": True})
        elif name == "ADC (RSD1_2)":
            context["check_type"] = "rsd1_2"
        elif name == "RSD All OFF":
            context.update({"rsd1": False, "rsd2": False})

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
            for line in res["log"].splitlines():
                logger.error(f"  --> [FAIL] {line}")
            log_event(logger, event=f"{stage_name}.step_failed", stage=stage_name, data={"case": name, "error": res["log"]})
            
            # Stage 2 특유의 실패 시 정리 로직
            if name != "RSD All OFF" and name != "Relay OFF":
                 logger.info("Cleaning up: Turning off RSD and Relay...")
                 RSDController().run({**context, "rsd1": False, "rsd2": False})
                 RelayController().run({**context, "target_state": "OFF"})
            
            return results 
        else:
            for line in res["log"].splitlines():
                logger.info(f"  --> [OK] {line}")
            
        time.sleep(0.1)
    
    return results


def run_stage_test(
    *,
    logger,
    io,
    db_server,
    vendor,
    product,
    stage_name: str = "stage3",
    adc_config: dict = {},
    relay_pin: int = None,
    relay_active_high: bool = True,
    label_config: dict = {}
) -> AggregatedResult:
    results = AggregatedResult(test=stage_name, code=0)
    
    common_steps = [
        ("Neighbor Scanner", NeighborScanner()),
        ("Communication Test", CommTester()),
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
        "label": label_config,
        "board_type": product if vendor in ["conalog", "nanoom"] else f"{vendor}_{product}"
    }

    logger.info(">>> Running Common Steps...")
    results = run_steps_sequentially(common_steps, context, logger, results)

    # Fill device info from globals (populated by NeighborScanner or DeviceVerifier)
    results.device_id = g.target_device.device_id

    if results.code != 0:
        return results

    # Determine board type from configuration (context)
    # Stage 2 is post-assembly, we trust the config.
    vendor = context.get("vendor", "unknown")
    product = context.get("product", "unknown")
    
    if vendor in ["conalog", "nanoom"]:
        board_type = product
    else:
        board_type = f"{vendor}_{product}"
    
    logger.info(f">>> Target Board: {board_type}. Running board-specific tests...")
    
    try:
        board_module = importlib.import_module(f"stage3.boards.{board_type}")
        board_results = board_module.run_stage_test(context)
        
        results.details.extend(board_results.details)
        results.code = board_results.code
        
        if results.code == 0:
            logger.info(">>> Running Final Steps (Mesh Config & Label Printer)...")
            final_steps = [
                ("Final Mesh Config", FinalMeshConfigurator()),
                ("Label Printer (Placeholder)", LabelPrinter()),
            ]
            results = run_steps_sequentially(final_steps, context, logger, results)
        
    except ImportError:
        logger.error(f"Test implementation for board '{board_type}' not found.")
        results.code = E_DEVICE_RECOGNITION_FAIL.code
    except Exception as e:
        logger.error(f"Error during board-specific test execution: {e}")
        results.code = -1

    return results
