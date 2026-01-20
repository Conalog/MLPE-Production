import sys
import os
import time
import json
import logging

# 상위 디렉토리 임포트 허용
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.solar_bridge import SolarBridgeClient

def main():
    # 로깅 설정
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    logger = logging.getLogger("diag_get_info")

    target_id = "0x9FFD2FCA"
    if len(sys.argv) > 1:
        target_id = sys.argv[1]

    # configs/server.json에서 브릿지 주소 정보 가져오기
    try:
        with open("configs/server.json", "r") as f:
            srv_cfg = json.load(f)
            host = srv_cfg.get("bridge_host", "localhost")
            port = srv_cfg.get("bridge_port", 1883)
    except Exception:
        host = "localhost"
        port = 1883

    print(f"--- GET_INFO Diagnostic Tool ---")
    print(f"Target Device: {target_id}")
    print(f"Solar Bridge: {host}:{port}")
    print("-" * 35)

    client = SolarBridgeClient(host=host, port=port, timeout=1.0)

    # 1. 스틱 목록 조회
    print("[1] Fetching stick list...")
    sticks = client.list_sticks(logger=logger)
    if not sticks:
        print("[-] Error: No sticks connected to Solar Bridge.")
        return

    print(f"[+] Found {len(sticks)} stick(s):")
    for s in sticks:
        print(f"    - UID: {s.get('uid')}, Port: {s.get('port')}")

    # 2. 각 스틱으로 REQ_GET_INFO 전송
    print("\n[2] Sending REQ_GET_INFO to each stick...")
    for s in sticks:
        uid = s.get("uid")
        if not uid: continue

        print(f"[*] Trying via stick: {uid}...")
        start_ts = time.time()
        info = client.get_device_info(target_id, uid, logger=logger)
        elapsed = time.time() - start_ts

        if info:
            print(f"[SUCCESS] Received response in {elapsed:.2f}s!")
            print(f"          Payload: {json.dumps(info, indent=4)}")
        else:
            print(f"[FAILURE] Timeout or no response from {target_id} via {uid} ({elapsed:.2f}s)")

    print("\nDiagnostic complete.")

if __name__ == "__main__":
    main()
