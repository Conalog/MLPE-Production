from typing import Optional
from stage1.types import Mlpe
from common.solar_bridge import SolarBridgeClient

# Global State
target_device = Mlpe()
bridge: Optional[SolarBridgeClient] = None
