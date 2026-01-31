# Image Build Steps (Ubuntu 24.04 Server LTS)

> 이 문서는 이미지(.img) 생성 당시 수행한 명령어 기록용입니다.

## 패키지 업데이트 및 필수 유틸
```bash
sudo apt update -y && sudo apt upgrade -y
sudo apt install net-tools -y
sudo apt install -y pkg-config libusb-1.0-0-dev libftdi1-dev libudev-dev -y
sudo apt install python-is-python3
sudo apt install python3-pip -y
sudo apt install python3-qrcode -y
sudo apt install python3-gpiozero -y
sudo apt install python3-rpi.gpio -y
sudo apt install python3-paho-mqtt -y
sudo apt install python3-numpy -y
sudo apt install python3-pillow -y
sudo apt install python3-packaging -y
```

## apt로 설치 불가한 Python 패키지
```bash
python3 -m pip install pocketbase --break-system-packages
```

## CUPS 설치
```bash
sudo apt install cups -y
sudo usermod -aG lpadmin $USER
sudo systemctl enable cups
sudo systemctl start cups
```

## Tailscale 설치
```bash
curl -fsSL https://tailscale.com/install.sh | sh
```

## J-Link / probe-rs 설정
```bash
curl --proto '=https' --tlsv1.2 -LsSf https://github.com/probe-rs/probe-rs/releases/latest/download/probe-rs-tools-installer.sh | sh
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="1366", MODE="0666", GROUP="dialout"' | sudo tee /etc/udev/rules.d/99-jlink.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo usermod -aG dialout $USER
sudo usermod -aG i2c $USER
```

## Font 설치
```bash
sudo apt install -y fonts-noto-cjk
sudo fc-cache -fv
```
