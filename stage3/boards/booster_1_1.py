from typing import Any
from stage3.steps import ADCResultChecker, RSDController, RelayController, DutyRatioTester, run_steps_sequentially
from stage3.types import AggregatedResult

def run_stage_test(context: dict[str, Any]) -> AggregatedResult:
    logger = context["logger"]
    stage_name = context.get("stage_name", "stage3")
    results = AggregatedResult(test=f"{stage_name}.booster_1_1", code=0)
    
    steps = [
        ("ADC Check (Before Relay)", ADCResultChecker()),
        ("Relay ON", RelayController()),
        ("ADC Check (After Relay)", ADCResultChecker()),
        ("RSD2 ON", RSDController()),
        ("ADC (RSD2)", ADCResultChecker()),
        ("RSD All OFF", RSDController()),
        ("Duty Ratio Test", DutyRatioTester()),
        ("Relay OFF", RelayController()),
    ]
    
    return run_steps_sequentially(steps, context, logger, results)
