from __future__ import annotations

import socket
import subprocess
import time
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .io_thread import IOThread

from common.test_base import TestCase
from .types import AggregatedResult, TestDetail
from . import globals as g
from common.logging_utils import log_event
from common.config_utils import load_json
from common.error_codes import (
    E_GPIO_UNAVAILABLE,
    E_JIG_ID_MISSING,
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


class StickChecker(TestCase):
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        if not g.bridge:
            return {"code": E_STICK_NOT_FOUND.code, "log": "Solar Bridge client not initialized"}
        try:
            sticks = g.bridge.list_sticks(logger=args.get("logger"))
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
    results = AggregatedResult(test="self", code=0)
    
    checkers = [
        ("GPIO Checker", GPIOChecker()),
        ("Jig ID Checker", JigIDChecker()),
        ("Stick Checker", StickChecker()),
    ]
    
    args = {
        "logger": logger,
        "io": io,
        "jig_id": jig_id,
        "config_path": config_path,
        "expected_jig_id": jig_id,
    }

    final_code = 0
    for name, checker in checkers:
        logger.info(f"Running: {name}...")
        res = checker.run(args)
        detail = TestDetail(case=name, parameter={"log": res["log"]}, code=res["code"])
        results.details.append(detail)

        if res["code"] != 0:
            final_code = res["code"]
            logger.error(f"  --> [FAIL] {res['log']}")
            log_event(logger, event="self_test.failed", stage="stage3", data={"case": name, "error": res["log"]})
        else:
            logger.info(f"  --> [OK] {res['log']}")

        time.sleep(0.1)

    results.code = final_code
    if final_code == 0:
        log_event(logger, event="self_test.ok", stage="stage3")
    
    return results
