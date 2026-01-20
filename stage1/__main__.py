from __future__ import annotations

import argparse
import sys

from common.config_utils import load_json, parse_jig_config, parse_stage1_pins
from stage1.app import Stage1Config, run_stage1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Stage 1 (생산 및 기본검증) - Raspberry Pi Jig Program")
    p.add_argument("--logs-dir", default="logs", help="로그 기본 디렉터리")
    p.add_argument("--jig-config", default="configs/jig.json", help="지그 설정 파일(JSON, jig id 전용)")
    p.add_argument("--io-config", default="configs/io.json", help="공용 IO 핀 설정 파일(JSON)")
    p.add_argument("--server-config", default="configs/server.json", help="서버 연결 설정 파일(JSON)")
    args = p.parse_args(argv)

    cfg = Stage1Config.from_json(
        jig_config_path=args.jig_config,
        io_config_path=args.io_config,
        server_config_path=args.server_config,
        logs_base_dir=args.logs_dir,
    )
    return run_stage1(cfg)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

