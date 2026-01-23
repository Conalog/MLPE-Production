from typing import Any
from stage3.steps import (
    run_steps_sequentially,
    RelayController,
    ADCResultChecker,
    RSDController,
    DutyRatioTester
)
from stage3.types import AggregatedResult

def run_stage_test(context: dict[str, Any]) -> AggregatedResult:
    results = AggregatedResult(test="stage3.booster_2_1", code=0)
    logger = context["logger"]
    
    steps = [
        ("ADC Check (Before Relay)", ADCResultChecker()),
        ("Relay ON", RelayController()),
        ("ADC Check (After Relay)", ADCResultChecker()),
        ("RSD1 ON", RSDController()),
        ("ADC (RSD1)", ADCResultChecker()),
        ("RSD1+2 ON", RSDController()),
        ("ADC (RSD1_2)", ADCResultChecker()),
        ("RSD All OFF", RSDController()),
        ("Duty Ratio Test", DutyRatioTester()),
        ("Relay OFF", RelayController()),
    ]
    
    return run_steps_sequentially(steps, context, logger, results)
