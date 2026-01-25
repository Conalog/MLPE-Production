import subprocess
import time
import os
import json
import logging
import numpy as np
import importlib
from typing import Any

from common.test_base import TestCase
from stage1.types import AggregatedResult, TestDetail
from common.logging_utils import log_event
from stage1.nrf52_ficr import NRF52FICR
from stage1 import globals as g
from common.error_codes import (
    E_VOLTAGE_12V_OUT_OF_RANGE,
    E_VOLTAGE_3V3_OUT_OF_RANGE,
    E_DEVICE_RECOGNITION_FAIL,
    E_FIRMWARE_DOWNLOAD_FAIL,
    E_FIRMWARE_UPLOAD_FAIL,
    E_DEVICE_COMMUNICATION_FAIL,
    E_ADC_VERIFICATION_FAIL,
    E_MESH_CONFIG_FAIL
)


class VoltageChecker(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        io = args["io"]
        v12, v33 = io.read_voltages()
        
        if not (11.0 <= v12 <= 13.5):
            return {"code": E_VOLTAGE_12V_OUT_OF_RANGE.code, "log": f"12V out of range: {v12:.2f}V"}
        if not (3.0 <= v33 <= 3.6):
            return {"code": E_VOLTAGE_3V3_OUT_OF_RANGE.code, "log": f"3.3V out of range: {v33:.2f}V"}
            
        return {"code": 0, "log": f"Voltages OK: 12V={v12:.2f}V, 3.3V={v33:.2f}V"}


class DeviceRecognizer(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            # 1. J-Link check
            list_proc = subprocess.run(["probe-rs", "list"], capture_output=True, text=True, timeout=5.0)
            if "J-Link" not in list_proc.stdout:
                return {"code": E_DEVICE_RECOGNITION_FAIL.code, "log": "No J-Link probe detected"}

            # 2. nRF52810 info
            info_proc = subprocess.run(
                ["probe-rs", "info", "--chip", "nRF52810_xxAA", "--protocol", "swd"],
                capture_output=True, text=True, timeout=10.0
            )
            combined_output = f"{info_proc.stdout} {info_proc.stderr}"
            if "Nordic VLSI ASA" not in combined_output:
                return {"code": E_DEVICE_RECOGNITION_FAIL.code, "log": "Device recognition failed: Nordic ID not found"}

            # 3. FICR Read
            read_proc = subprocess.run(
                ["probe-rs", "read", "--chip", "nRF52810_xxAA", "--protocol", "swd", "b32", "0x10000000", "128"],
                capture_output=True, text=True, timeout=10.0
            )
            
            if read_proc.returncode != 0:
                return {"code": E_DEVICE_RECOGNITION_FAIL.code, "log": "Failed to read FICR"}

            words = []
            for line in read_proc.stdout.splitlines():
                content = line.split(":", 1)[1] if ":" in line else line
                for val in content.split():
                    try:
                        clean_val = val.strip(",;").lower()
                        if clean_val.startswith("0x"): words.append(int(clean_val, 16))
                        elif all(c in "0123456789abcdef" for c in clean_val) and len(clean_val) >= 4:
                            words.append(int(clean_val, 16))
                    except ValueError: continue

            ficr = NRF52FICR(words)
            ficr_dict = ficr.as_dict()
            
            # 전역 MLPE 상태 업데이트
            g.target_device.ficr = ficr_dict
            addr = ficr_dict.get("device_addr", "000000000000")
            g.target_device.device_id = addr.upper() # Full 6-byte address
            
            return {"code": 0, "log": f"Device recognized: {g.target_device.device_id}"}
            
        except Exception as e:
            return {"code": E_DEVICE_RECOGNITION_FAIL.code, "log": f"Recognition error: {str(e)}"}


class FirmwareDownloader(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        db_server = args["db_server"]
        vendor = args["vendor"]
        product = args["product"]
        fw_dir = "./firmware"
        if not os.path.exists(fw_dir): os.makedirs(fw_dir)

        # Bootloader
        res_boot = db_server.download_firmware(vendor, product, fw_type="bootloader")
        if not res_boot:
            return {"code": E_FIRMWARE_DOWNLOAD_FAIL.code, "log": f"Failed to download bootloader for {vendor}/{product}"}
        boot_bin, boot_ver = res_boot
        boot_path = os.path.join(fw_dir, f"bootloader_{boot_ver}.bin")
        
        # Application
        res_app = db_server.download_firmware(vendor, product, fw_type="application")
        if not res_app:
            return {"code": E_FIRMWARE_DOWNLOAD_FAIL.code, "log": f"Failed to download application for {vendor}/{product}"}
        app_bin, app_ver = res_app
        app_path = os.path.join(fw_dir, f"{vendor}_{product}_application_{app_ver}.bin")

        try:
            with open(boot_path, "wb") as f: f.write(boot_bin)
            with open(app_path, "wb") as f: f.write(app_bin)
            args["boot_path"] = boot_path
            args["app_path"] = app_path
            return {"code": 0, "log": f"Downloaded Bootloader({boot_ver}) and App({app_ver})"}
        except Exception as e:
            return {"code": E_FIRMWARE_DOWNLOAD_FAIL.code, "log": f"Save error: {str(e)}"}


class FirmwareUploader(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        boot_path = args["boot_path"]
        app_path = args["app_path"]
        
        try:
            # Erase
            subprocess.run(["probe-rs", "erase", "--chip", "nRF52810_xxAA", "--speed", "2000"], check=True, timeout=20.0, capture_output=True)
            
            # Flash App 1, App 2, Boot
            commands = [ (app_path, "0x4000", "app"), (app_path, "0x21000", "app"), (boot_path, "0x0", "bootloader") ]
            logs = []
            for path, addr, name in commands:
                subprocess.run([
                    "probe-rs", "download", path, "--chip", "nRF52810_xxAA", 
                    "--speed", "2000",
                    "--binary-format", "bin", "--base-address", addr
                ], check=True, timeout=30.0, capture_output=True)
                logs.append(f"Flash successful: {name} binary at {addr}")
                if addr == "0x0": time.sleep(0.3)
            
            # Reset
            subprocess.run(["probe-rs", "reset", "--chip", "nRF52810_xxAA"], timeout=10.0, capture_output=True)
            return {"code": 0, "log": "\n".join(logs)}
        except Exception as e:
            return {"code": E_FIRMWARE_UPLOAD_FAIL.code, "log": f"Upload error: {str(e)}"}


class CommTester(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        if not g.target_device.device_id:
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": "Device ID not found. Run recognition first."}
            
        device_id_hex = g.target_device.device_id
        
        if not g.bridge:
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": "Solar Bridge client not initialized."}

        for attempt in range(3):
            sticks = g.bridge.list_sticks()
            for s in sticks:
                uid = s.get("uid")
                if not uid: continue
                info = g.bridge.get_device_info(device_id_hex, uid)
                if info:
                    # 전역 MLPE 상태 업데이트
                    g.target_device.info = info
                    args["stick_uid"] = uid # ADC Tester에서 필요할 수 있지만 일단 globals에 넣을까 고민 중
                    return {"code": 0, "log": f"Comm verified via {uid} (ID: {device_id_hex})"}
            time.sleep(0.7)
            
        return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": f"Device {device_id_hex} did not respond to REQ_GET_INFO"}


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
            return {"code": 0, "log": log_msg}
        except Exception as e:
            return {"code": E_DEVICE_COMMUNICATION_FAIL.code, "log": f"RSD control error: {e}"}


class ADCResultChecker(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        target_id = g.target_device.device_id
        stick_uid = args.get("stick_uid")
        check_type = args.get("check_type", "baseline")
        stage = args.get("stage", "stage1")
        adc_config = args.get("adc_config", {})

        if not target_id or not stick_uid:
            return {"code": E_ADC_VERIFICATION_FAIL.code, "log": "Target ID or Stick UID missing"}

        # Board type determination
        board_type = args.get("board_type")
        if not board_type:
             vendor = args.get("vendor", "unknown")
             product = args.get("product", "unknown")
             board_type = product if vendor == "conalog" else f"{vendor}_{product}"

        ranges = adc_config.get(stage, {}).get(board_type, {}).get(check_type, {})
        if not ranges:
            return {"code": E_ADC_VERIFICATION_FAIL.code, "log": f"ADC ranges not found for {stage}/{board_type}/{check_type}"}

        # Collect samples
        samples = g.bridge.dump_adc(target_id, stick_uid, duration=1.0, logger=args["logger"])
        if not samples:
            return {"code": E_ADC_VERIFICATION_FAIL.code, "log": "Failed to collect ADC samples"}

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

        res_log = ", ".join(result_details)
        if errors:
            return {"code": E_ADC_VERIFICATION_FAIL.code, "log": f"FAILED ({check_type}): " + "; ".join(errors)}
        else:
            return {"code": 0, "log": f"PASSED ({check_type}): {res_log}"}


class MeshConfigurator(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        target_id = g.target_device.device_id
        stick_uid = args.get("stick_uid")

        if not target_id:
            return {"code": E_MESH_CONFIG_FAIL.code, "log": "Device ID (Target ID) not found."}
        if not stick_uid:
            return {"code": E_MESH_CONFIG_FAIL.code, "log": "Stick UID not found in context. Comm Tester must run first."}

        resp = g.bridge.set_mesh_config(target_id, stick_uid, logger=args.get("logger"))
        if resp is None:
            return {"code": E_MESH_CONFIG_FAIL.code, "log": f"Mesh config timeout: No response from {target_id}"}
            
        return {"code": 0, "log": f"Mesh config updated for {target_id}"}


def run_steps_sequentially(
    steps: list[tuple[str, TestCase]],
    context: dict[str, Any],
    logger: logging.Logger,
    results: AggregatedResult
) -> AggregatedResult:
    total_steps = len(steps)
    stage_name = context.get("stage", "stage1")
    
    for i, (name, step) in enumerate(steps, 1):
        # Step specific overrides
        if name == "ADC (Baseline)": context["check_type"] = "baseline"
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
        
        if res["code"] != 0:
            results.code = res["code"]
            for line in res["log"].splitlines():
                logger.error(f"  --> [FAIL] {line}")
            log_event(logger, event=f"{stage_name}.step_failed", stage=stage_name, data={"case": name, "error": res["log"]})
            return results # Stop sequence on failure
        else:
            for line in res["log"].splitlines():
                logger.info(f"  --> [OK] {line}")
            
            if name == "Comm Tester":
                logger.info("Comm Tester OK. Waiting 3s for stabilization...")
                time.sleep(3.0)
            
        time.sleep(0.1)
    
    return results


def run_stage_test(
    *,
    logger,
    io,
    db_server,
    vendor,
    product,
    stage_name: str = "stage1",
    adc_config: dict = {}
) -> AggregatedResult:
    results = AggregatedResult(test=stage_name, code=0)
    
    common_steps = [
        ("Voltage Checker", VoltageChecker()),
        ("Device Recognizer", DeviceRecognizer()),
        ("Firmware Downloader", FirmwareDownloader()),
        ("Firmware Uploader", FirmwareUploader()),
        ("Comm Tester", CommTester()),
    ]
    
    context = {
        "logger": logger,
        "io": io,
        "db_server": db_server,
        "vendor": vendor,
        "product": product,
        "stage": stage_name,
        "adc_config": adc_config,
        "board_type": product if vendor == "conalog" else f"{vendor}_{product}"
    }

    logger.info(">>> Running Common Steps...")
    results = run_steps_sequentially(common_steps, context, logger, results)
    
    # Fill device info from globals (populated by DeviceRecognizer)
    results.device_id = g.target_device.device_id

    if results.code != 0:
        return results

    # Determine board type from configuration (context)
    # Stage 1 is initial flashing, so we trust the config more than wireless info.
    vendor = context.get("vendor", "unknown")
    product = context.get("product", "unknown")
    
    if vendor in ["conalog", "nanoom"]:
        board_type = product
    else:
        board_type = f"{vendor}_{product}"
    
    logger.info(f">>> Target Board: {board_type}. Running board-specific tests...")
    
    try:
        board_module = importlib.import_module(f"stage1.boards.{board_type}")
        board_results = board_module.run_stage_test(context)
        
        # Merge board results into main results
        results.details.extend(board_results.details)
        results.code = board_results.code
        
    except ImportError:
        logger.error(f"Test implementation for board '{board_type}' not found.")
        results.code = E_DEVICE_RECOGNITION_FAIL.code # Or a more specific error
    except Exception as e:
        logger.error(f"Error during board-specific test execution: {e}")
        results.code = -1

    return results
