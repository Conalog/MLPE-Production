import qrcode
from PIL import Image

class QRCodeGenerator:
    """
    A class to generate QR codes for device IDs.
    """
    def __init__(self):
        self.base_url = "http://v.conalog.com/d/"

    def generate_qrcode(self, device_id: str) -> Image.Image:
        """
        Generates a QR code image for a given device ID.
        
        Args:
            device_id (str): A 12-character device ID string.
            
        Returns:
            PIL.Image.Image: The generated QR code image.
            
        Raises:
            ValueError: If the device_id is not 12 characters long.
        """
        if len(device_id) != 12:
            raise ValueError(f"device_id must be 12 characters long, got {len(device_id)}")
        
        url = f"{self.base_url}{device_id}"
        
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        return img

if __name__ == "__main__":
    import random
    import string
    
    # Generate a random 12-character device ID
    random_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    print(f"Generating QR code for random device ID: {random_id}")
    
    generator = QRCodeGenerator()
    try:
        qr_img = generator.generate_qrcode(random_id)
        filename = f"qr_{random_id}.png"
        qr_img.save(filename)
        print(f"QR code saved as: {filename}")
    except Exception as e:
        print(f"Error: {e}")
