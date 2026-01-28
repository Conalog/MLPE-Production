import os
import subprocess
import time
import json
from typing import Any, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont
import qrcode

def load_label_profiles(path: str = "configs/label_profiles.json") -> dict[str, Any]:
    """Loads label profiles from a JSON file."""
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)

def mm_to_px(mm: float, dpi: int = 300) -> int:
    mm_to_dots = dpi / 25.4
    return int(round(mm * mm_to_dots))

def draw_text_bold(draw: ImageDraw.ImageDraw, xy: Tuple[int, int], text: str, font: Any, fill="black", thickness=2):
    x, y = xy
    offsets = [(0, 0), (1, 0), (0, 1), (1, 1)]
    if thickness >= 3:
        offsets += [(-1, 0), (0, -1), (-1, -1)]
    for dx, dy in offsets:
        draw.text((x + dx, y + dy), text, font=font, fill=fill)

def to_mono(img: Image.Image, threshold: int = 160) -> Image.Image:
    """Convert to 1-bit monochrome for stable label printing."""
    gray = img.convert("L")
    bw = gray.point(lambda p: 0 if p < threshold else 255, mode="1")
    return bw

def img_to_gfa(img_bw_1bit: Image.Image) -> str:
    """PIL 1-bit image -> ZPL ^GFA ASCII-HEX format."""
    if img_bw_1bit.mode != "1":
        raise ValueError("img must be 1-bit (mode '1')")
    w, h = img_bw_1bit.size
    bytes_per_row = (w + 7) // 8
    total_bytes = bytes_per_row * h
    
    pixels = img_bw_1bit.load()
    rows = []
    for y in range(h):
        row = bytearray(bytes_per_row)
        for x in range(w):
            is_black = (pixels[x, y] == 0)
            if is_black:
                byte_index = x // 8
                bit_index = 7 - (x % 8)
                row[byte_index] |= (1 << bit_index)
        rows.append(row)
    
    hexdata = "".join(r.hex().upper() for r in rows)
    return f"^GFA,{total_bytes},{total_bytes},{bytes_per_row},{hexdata}"

class LabelGenerator:
    def __init__(self, font_path: str = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
        self.font_path = font_path
        self._load_fonts()

    def _load_fonts(self):
        try:
            self.font_big = ImageFont.truetype(self.font_path, 48)
            self.font_mid = ImageFont.truetype(self.font_path, 34)
            self.font_small = ImageFont.truetype(self.font_path, 30)
        except Exception:
            self.font_big = ImageFont.load_default()
            self.font_mid = ImageFont.load_default()
            self.font_small = ImageFont.load_default()

    def build_label_png(
        self,
        data: dict[str, Any],
        out_png: str,
        profile: dict[str, Any]
    ):
        settings = profile.get("printer_settings", {})
        layout = profile.get("layout", {})
        items = layout.get("items", [])
        
        dpi = settings.get("paper_size_dpi", 300)
        width_mm = settings.get("paper_size_width_mm", 70.0)
        height_mm = settings.get("paper_size_height_mm", 35.0)

        W = mm_to_px(width_mm, dpi)
        H = mm_to_px(height_mm, dpi)
        img = Image.new("RGB", (W, H), "white")
        draw = ImageDraw.Draw(img)

        fonts = {
            "big": self.font_big,
            "mid": self.font_mid,
            "small": self.font_small
        }

        for item in items:
            itype = item.get("type")
            pos = item.get("pos", [0, 0])
            data_key = item.get("data_key")
            
            # Validation: If a data_key is specified, it MUST exist in the provided data and not be None/empty
            if data_key:
                val = data.get(data_key)
                if val is None or (isinstance(val, str) and val.strip() == ""):
                    raise ValueError(f"Required label data field '{data_key}' is missing or empty in the configuration.")

            # X coordinate handling (negative means right-aligned)
            x_cfg = pos[0]
            y_cfg = pos[1]
            
            if itype == "text":
                font_key = item.get("font", "mid")
                font = fonts.get(font_key, self.font_mid)
                prefix = item.get("prefix", "")
                val = str(data[data_key]) if data_key else ""
                text = f"{prefix}{val}"
                
                # Check for bold override
                thickness = 2 if item.get("bold", True) else 1
                
                # Render
                draw_text_bold(draw, (x_cfg, y_cfg), text, font, thickness=thickness)
                
            elif itype == "qr":
                # Default to qr_text if not specified, but usually it is in config
                qr_text = data[data_key if data_key else "qr_text"]
                if not qr_text:
                    raise ValueError("QR text data is empty.")
                    
                qr = qrcode.QRCode(border=1, box_size=10)
                qr.add_data(qr_text)
                qr.make(fit=True)
                qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
                
                size_mm = item.get("size_mm", 20)
                px = mm_to_px(size_mm, dpi)
                qr_img = qr_img.resize((px, px))
                
                # Handle relative X
                real_x = W - px + x_cfg if x_cfg < 0 else x_cfg
                img.paste(qr_img, (real_x, y_cfg))
                
            elif itype == "logo":
                # Path might be provided in data or config
                path = data.get(data_key) if data_key else item.get("path")
                if not path:
                    continue # Skip if no path given at all
                    
                if not os.path.exists(path):
                    raise FileNotFoundError(f"Logo file not found: {path}")
                    
                size_mm = item.get("size_mm", [14, 14])
                try:
                    logo = Image.open(path).convert("RGBA")
                    max_w = mm_to_px(size_mm[0], dpi)
                    max_h = mm_to_px(size_mm[1], dpi)
                    logo.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                    
                    # Handle relative X
                    real_x = W - logo.size[0] + x_cfg if x_cfg < 0 else x_cfg
                    img.paste(logo, (real_x, y_cfg), logo)
                except Exception as e:
                    raise RuntimeError(f"Failed to process logo: {e}")

        img.save(out_png)
        return out_png

def generate_zpl_from_png(png_path: str, profile: dict[str, Any], threshold: int = 160) -> str:
    """Converts a PNG label to a complete ZPL string using profile settings."""
    img = Image.open(png_path)
    bw = to_mono(img, threshold=threshold)
    gfa = img_to_gfa(bw)
    
    settings = profile.get("printer_settings", {})
    
    # Profile parameters
    darkness = settings.get("brightness", 25)
    print_speed = settings.get("print_speed", 2)
    slew_speed = settings.get("slew_speed", 2)
    backfeed_speed = settings.get("backfeed_speed", 2)
    home_x = settings.get("label_home_x", 0)
    home_y = settings.get("label_home_y", 15)
    
    dpi = settings.get("paper_size_dpi", 300)
    width_mm = settings.get("paper_size_width_mm", 70.0)
    print_width = settings.get("print_width_dots", int(width_mm * (dpi / 25.4)))

    zpl = "\n".join([
        "^XA",
        "^CI28",
        f"~SD{darkness}",
        f"^PR{print_speed},{slew_speed},{backfeed_speed}",
        f"^LH{home_x},{home_y}",
        f"^PW{print_width}",
        f"^LL{bw.size[1] + home_y + 15}", # Label Length based on image height + buffer
        "^FO0,0",
        gfa,
        "^FS",
        "^XZ",
    ]) + "\n"
    return zpl

def send_zpl_to_printer(zpl: str, printer_name: str = "ZD421"):
    """Sends ZPL data to the printer via lp command."""
    subprocess.run(["lp", "-d", printer_name], input=zpl.encode("utf-8"), check=True)
