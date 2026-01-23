import sys
from .app import run_stage3, Stage3Config

if __name__ == "__main__":
    # 기본 경로 설정
    jig_cfg = "configs/jig.json"
    io_cfg = "configs/io_pins.json"
    server_cfg = "configs/server.json"
    logs_dir = "logs"

    cfg = Stage3Config.from_json(
        jig_config_path=jig_cfg,
        io_config_path=io_cfg,
        server_config_path=server_cfg,
        logs_base_dir=logs_dir
    )
    sys.exit(run_stage3(cfg))
