from __future__ import annotations

import socket
import subprocess
import time
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from stage1.io_thread import IOThread

from common.test_base import TestCase
from stage1.types import AggregatedResult, TestDetail
from stage1 import globals as g
from common.logging_utils import log_event
from common.config_utils import load_json
from common.error_codes import (
    E_ADS1115_NOT_FOUND,
    E_GPIO_UNAVAILABLE,
    E_JIG_ID_MISSING,
    E_JLINK_NOT_FOUND,
    E_STICK_NOT_FOUND,
    OK,
)


def check_internet(timeout_s: float = 2.0) -> bool:
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=timeout_s):
            return True
    except Exception:
        return False


class GPIOChecker(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            import RPi.GPIO  # noqa: F401
            return {"code": 0, "log": "GPIO is available"}
        except Exception as e:
            return {"code": E_GPIO_UNAVAILABLE.code, "log": f"GPIO unavailable: {str(e)}"}


class ADS1115Checker(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        io: IOThread = args["io"]
        adc_ok, adc_err = io.get_ads1115_status()
        if adc_ok:
            return {"code": 0, "log": "ADS1115 sensor is connected"}
        else:
            return {"code": E_ADS1115_NOT_FOUND.code, "log": adc_err or "ADS1115 not found"}


class JigIDChecker(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        config_path = args["config_path"]
        expected_jig_id = args["expected_jig_id"]
        try:
            data = load_json(config_path)
            v = data.get("jig_id")
            if v == expected_jig_id:
                return {"code": 0, "log": f"Jig ID is valid : {v}"}
            else:
                return {"code": E_JIG_ID_MISSING.code, "log": f"Jig ID mismatch (expected: {expected_jig_id}, found: {v})"}
        except Exception as e:
            return {"code": E_JIG_ID_MISSING.code, "log": f"Jig ID check error: {str(e)}"}


class JLinkChecker(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = subprocess.run(["probe-rs", "list"], capture_output=True, text=True, timeout=5.0)
            if "J-Link" in result.stdout:
                return {"code": 0, "log": "J-Link is connected"}
            else:
                return {"code": E_JLINK_NOT_FOUND.code, "log": "J-Link probe not found"}
        except Exception as e:
            return {"code": E_JLINK_NOT_FOUND.code, "log": f"J-Link check error: {str(e)}"}


class StickChecker(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        if not g.bridge:
            return {"code": E_STICK_NOT_FOUND.code, "log": "Solar Bridge client not initialized"}
        try:
            sticks = g.bridge.list_sticks()
            if sticks:
                version = sticks[0].get("version", "unknown")
                return {"code": 0, "log": f"Stick is connected. Version : {version}"}
            else:
                return {"code": E_STICK_NOT_FOUND.code, "log": "No active sticks found"}
        except Exception as e:
            return {"code": E_STICK_NOT_FOUND.code, "log": f"Stick check error: {str(e)}"}


def run_self_test(
    *,
    logger,
    io: "IOThread",
    jig_id: str,
    config_path: str,
) -> AggregatedResult:
    """
    Executes the self-test sequence and returns an aggregated result.
    """
    results = AggregatedResult(test="self", code=0)
    
    checkers = [
        ("GPIO Checker", GPIOChecker()),
        ("ADS1115 Checker", ADS1115Checker()),
        ("Jig ID Checker", JigIDChecker()),
        ("J-Link Checker", JLinkChecker()),
        ("Stick Checker", StickChecker()),
    ]
    
    args = {
        "io": io,
        "jig_id": jig_id,
        "config_path": config_path,
        "expected_jig_id": jig_id,
    }

    final_code = 0
    for name, checker in checkers:
        logger.info(f"Running: {name}...")
        res = checker.run(args)
        detail = TestDetail(case=name, log=res["log"], code=res["code"])
        results.details.append(detail)

        if res["code"] != 0:
            final_code = res["code"]
            logger.error(f"  --> [FAIL] {res['log']}")
            log_event(logger, event="self_test.failed", stage="stage1", data={"case": name, "error": res["log"]})
        else:
            logger.info(f"  --> [OK] {res['log']}")

        time.sleep(0.1)

    results.code = final_code
    if final_code == 0:
        log_event(logger, event="self_test.ok", stage="stage1")
    
    return results


