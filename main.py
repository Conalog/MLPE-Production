from __future__ import annotations

import argparse
import sys
import json
import importlib
from pathlib import Path

def load_stage_info(config_path: str) -> int:
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return int(data.get("stage", 1))
    except Exception as e:
        print(f"Error reading config {config_path}: {e}")
        return 1

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Production Jig Root Entry Point", add_help=False)
    parser.add_argument("--jig-config", default="configs/jig.json", help="Path to jig config")
    args, unknown = parser.parse_known_args(argv)

    stage = load_stage_info(args.jig_config)
    print(f">>> Detected Stage: {stage}")

    stage_module_name = f"stage{stage}.__main__"
    
    try:
        # Check if directory exists
        if not Path(f"stage{stage}").is_dir():
            print(f"Error: Stage {stage} directory not found.")
            return 1

        module = importlib.import_module(stage_module_name)
        if hasattr(module, "main"):
            print(f">>> Launching Stage {stage}...")
            return module.main(argv)
        else:
            print(f"Error: Stage {stage} module does not have a main function.")
            return 1
    except ImportError as e:
        print(f"Error: Failed to import stage {stage} (Module: {stage_module_name}).")
        print(f"Details: {e}")
        return 1
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
