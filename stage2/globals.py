from typing import Optional
from .types import Mlpe
from common.solar_bridge import SolarBridgeClient

# Global State
target_device = Mlpe()
bridge: Optional[SolarBridgeClient] = None
