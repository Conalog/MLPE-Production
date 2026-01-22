#!/bin/bash

# ==============================================================================
# Conalog Production Jig - Environment Setup Script
# Target OS: Ubuntu Server 24.04.3 LTS (Raspberry Pi)
# ==============================================================================

set -e

echo ">>> [1/7] Updating system packages..."
sudo apt update
sudo apt install -y \
    python3-pip \
    python3-venv \
    i2c-tools \
    libusb-1.0-0-dev \
    git \
    curl \
    pkg-config \
    build-essential \
    libudev-dev

echo ">>> [2/7] Installing Tailscale (Remote Access)..."
if ! command -v tailscale &> /dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
    echo "Tailscale installed. Please run 'sudo tailscale up' after reboot to authenticate."
else
    echo "Tailscale is already installed."
fi

echo ">>> [3/7] Installing probe-rs (Firmware Toolchain)..."
if ! command -v probe-rs &> /dev/null; then
    curl --proto '=https' --tlsv1.2 -sSf https://probe.rs/install.sh | sh
    # Add to PATH for the current session
    export PATH="$HOME/.cargo/bin:$PATH"
else
    echo "probe-rs is already installed."
fi

echo ">>> [4/7] Setting up Python Virtual Environment..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "Virtual environment created."
fi
source .venv/bin/bin/activate || source .venv/bin/activate
pip install --upgrade pip
echo "Installing Python dependencies (including PocketBase SDK)..."
pip install -r requirements.txt

echo ">>> [5/7] Configuring Hardware Permissions (udev)..."
# 1. J-Link udev rules
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="1366", MODE="0666", GROUP="dialout"' | sudo tee /etc/udev/rules.d/99-jlink.rules
# 2. probe-rs recommended rules (general CMSIS-DAP / ST-Link etc)
# Note: probe-rs actually provides a udev rule file, but we'll add basic ones for J-Link
sudo udevadm control --reload-rules
sudo udevadm trigger

echo ">>> [6/7] Adding user to hardware groups..."
sudo usermod -aG dialout $USER
sudo usermod -aG i2c $USER
# Raspberry Pi Ubuntu specific: enabling I2C might require editing /boot/firmware/config.txt
if ! grep -q "dtparam=i2c_arm=on" /boot/firmware/config.txt; then
    echo "dtparam=i2c_arm=on" | sudo tee -a /boot/firmware/config.txt
    echo "I2C enabled in config.txt (requires reboot)"
fi

echo ">>> [7/7] Setup Complete!"
echo "=============================================================================="
echo "Next steps:"
echo "1. Reboot your Raspberry Pi: 'sudo reboot'"
echo "2. After reboot, run: 'sudo tailscale up' for remote access."
echo "3. Activate venv: 'source .venv/bin/activate'"
echo "4. Run the program: 'python3 main.py'"
echo "=============================================================================="
