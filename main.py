from __future__ import annotations

import os
import sys
import time
import subprocess
import signal
import logging
from typing import Any
from pathlib import Path

from common.config_utils import load_json, get_hostname_jig_id, ConfigSyncThread
from common.db_server import create_db_server
from common.logging_utils import build_logger, ensure_log_dir

# Global flags for stage management
stage_change_requested = False
target_stage_val = None

def on_stage_changed(new_stage: int) -> None:
    global stage_change_requested, target_stage_val
    print(f"\n[CALLBACK] on_stage_changed triggered with stage: {new_stage}")
    stage_change_requested = True
    target_stage_val = new_stage

def main() -> int:
    global stage_change_requested, target_stage_val
    
    # 1. Setup logging for supervisor
    log_dir = ensure_log_dir("logs", "supervisor")
    logger = build_logger(name="supervisor", log_dir=log_dir, console=True, level=logging.INFO)
    
    logger.info("="*50)
    logger.info("Starting Production Jig Supervisor")
    logger.info("="*50)

    # 2. Load configurations
    try:
        server_cfg = load_json("configs/server.json")
        jig_cfg_local = load_json("configs/jig.json")
    except Exception as e:
        logger.error(f"Failed to load configurations: {e}")
        return 1
        
    # Jig ID (Always use hostname as source of truth)
    from common.config_utils import atomic_save_json
    jig_id = get_hostname_jig_id()
    
    if jig_cfg_local.get("jig_id") != jig_id:
        jig_cfg_local["jig_id"] = jig_id
        try:
            atomic_save_json("configs/jig.json", jig_cfg_local)
            logger.info(f"Config jig_id updated to match hostname: {jig_id}")
        except Exception as e:
            logger.warning(f"Failed to update configs/jig.json: {e}")
    
    logger.info(f"Using System Jig ID: {jig_id}")
    
    # 3. Initialize DB Server
    db_server = create_db_server(server_cfg, jig_id=jig_id)
    if not db_server:
        logger.error("Failed to initialize DB Server")
        return 1

    # 처음 실행 시 서버에서 최신 Config 다운로드 (한 번 수행)
    logger.info(f"Fetching initial configuration from server for {jig_id}...")
    initial_config = db_server.get_jig_config(jig_id, logger=logger)
    if initial_config:
        try:
            atomic_save_json("configs/jig.json", initial_config)
            logger.info("Initial configuration synced and saved to configs/jig.json")
        except Exception as e:
            logger.warning(f"Failed to save initial configuration: {e}")
    else:
        logger.warning("Could not fetch initial configuration from server. Using local version.")

    # 4. Start ConfigSyncThread
    sync_thread = ConfigSyncThread(
        db_server=db_server,
        jig_id=jig_id,
        config_path="configs/jig.json",
        interval=3.0,
        on_stage_changed=on_stage_changed,
        logger=logger
    )
    sync_thread.start()

    # 5. Signal Handlers for Supervisor itself
    def supervisor_signal_handler(signum, frame):
        logger.info(f"Supervisor received signal {signum}. Shutting down...")
        sync_thread.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, supervisor_signal_handler)
    signal.signal(signal.SIGTERM, supervisor_signal_handler)

    # 6. Main Supervisor Loop
    while True:
        # Load current stage from config
        try:
            jig_cfg = load_json("configs/jig.json")
            current_stage = int(jig_cfg.get("stage", 1))
        except Exception:
            current_stage = 1
            
        logger.info(f">>> Launching Stage {current_stage} process...")
        
        # Start stage app as subprocess
        # We use sys.executable to ensure we use the same python interpreter
        cmd = [sys.executable, "-m", f"stage{current_stage}"]
        
        try:
            # We want to use the same environment but can add/modify if needed
            env = os.environ.copy()
            env["PYTHONPATH"] = f"{os.getcwd()}:{env.get('PYTHONPATH', '')}"
            # Force lgpio factory to avoid /dev/mem access issues (no root required)
            env["GPIOZERO_PIN_FACTORY"] = "lgpio"
            
            process = subprocess.Popen(cmd, env=env)
        except Exception as e:
            logger.error(f"Failed to start stage process: {e}")
            time.sleep(5.0) # Wait before retry
            continue
        
        stage_change_requested = False
        
        # Wait for process to exit or stage change request
        try:
            while process.poll() is None:
                if stage_change_requested:
                    logger.info(f"!!! Stage Change Detected: -> {target_stage_val}")
                    logger.info(f"Requesting Graceful Shutdown of Stage {current_stage} (sending SIGTERM)...")
                    
                    # Graceful shutdown: send SIGTERM and wait
                    process.send_signal(signal.SIGTERM)
                    
                    # Wait for the process to exit (gracefully)
                    # We might want a timeout here to force kill if it hangs
                    try:
                        process.wait(timeout=30.0)
                    except subprocess.TimeoutExpired:
                        logger.warning(f"Stage {current_stage} did not exit gracefully. Force killing...")
                        process.kill()
                    break
                
                time.sleep(1.0)
        except KeyboardInterrupt:
            logger.info("Supervisor interrupted. Shutting down child...")
            process.terminate()
            process.wait()
            raise

        exit_code = process.wait()
        logger.info(f"Stage {current_stage} process exited with code {exit_code}")
        
        # Reset target_stage_val after we handled it
        if stage_change_requested:
            logger.info(f"Preparing to switch to Stage {target_stage_val}...")
            time.sleep(1.0) # Brief pause
        else:
            # If it exited naturally without stage change, restart after delay
            logger.info("Process exited naturally. Restarting in 3 seconds...")
            time.sleep(3.0)

if __name__ == "__main__":
    sys.exit(main())
