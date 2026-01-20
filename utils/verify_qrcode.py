import sys
import os

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from common.qrcode_utils import QRCodeGenerator

def test_qrcode_generator():
    generator = QRCodeGenerator()
    
    # Test valid device ID
    device_id = "ABC123DEF456"
    print(f"Testing with device_id: {device_id}")
    try:
        img = generator.generate_qrcode(device_id)
        print(f"Success: QR code generated. Image size: {img.size}")
        # Save for manual check if needed
        # img.save("test_qr.png")
    except Exception as e:
        print(f"Failed: {e}")
        return False

    # Test invalid device ID (too short)
    device_id_short = "ABC123"
    print(f"Testing with device_id: {device_id_short}")
    try:
        generator.generate_qrcode(device_id_short)
        print("Failed: Should have raised ValueError for short ID")
        return False
    except ValueError as e:
        print(f"Success: Caught expected error: {e}")

    # Test invalid device ID (too long)
    device_id_long = "ABC123DEF4567"
    print(f"Testing with device_id: {device_id_long}")
    try:
        generator.generate_qrcode(device_id_long)
        print("Failed: Should have raised ValueError for long ID")
        return False
    except ValueError as e:
        print(f"Success: Caught expected error: {e}")

    return True

if __name__ == "__main__":
    if test_qrcode_generator():
        print("\nAll tests passed!")
        sys.exit(0)
    else:
        print("\nSome tests failed!")
        sys.exit(1)
