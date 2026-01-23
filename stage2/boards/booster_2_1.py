from typing import Any
from stage2.steps import ADCResultChecker, RSDController, RelayController, DutyRatioTester, run_steps_sequentially
from stage2.types import AggregatedResult

def run_stage_test(context: dict[str, Any]) -> AggregatedResult:
    logger = context["logger"]
    stage_name = context.get("stage_name", "stage2")
    results = AggregatedResult(test=f"{stage_name}.booster_2_1", code=0)
    
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
