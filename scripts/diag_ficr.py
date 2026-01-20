import subprocess
import os

def diagnose():
    print("--- probe-rs info ---")
    proc_info = subprocess.run(
        ["probe-rs", "info", "--chip", "nRF52810_xxAA", "--protocol", "swd"],
        capture_output=True, text=True
    )
    print(f"STDOUT:\n{proc_info.stdout}")
    print(f"STDERR:\n{proc_info.stderr}")

    print("\n--- probe-rs read b32 (FICR) ---")
    proc_read = subprocess.run(
        ["probe-rs", "read", "--chip", "nRF52810_xxAA", "--protocol", "swd", "b32", "0x10000000", "128"],
        capture_output=True, text=True
    )
    print(f"STDOUT:\n{proc_read.stdout}")
    print(f"STDERR:\n{proc_read.stderr}")
    print(f"Return Code: {proc_read.returncode}")

    # Raw dump to file for persistent checking
    with open("probe_rs_diagnostic.log", "w") as f:
        f.write("INFO STDOUT:\n" + proc_info.stdout + "\n")
        f.write("INFO STDERR:\n" + proc_info.stderr + "\n")
        f.write("READ STDOUT:\n" + proc_read.stdout + "\n")
        f.write("READ STDERR:\n" + proc_read.stderr + "\n")

if __name__ == "__main__":
    diagnose()
