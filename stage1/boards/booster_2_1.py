from typing import Any
from stage1.steps import ADCResultChecker, RSDController, MeshConfigurator, run_steps_sequentially
from stage1.types import AggregatedResult

def run_stage_test(context: dict[str, Any]) -> AggregatedResult:
    logger = context["logger"]
    stage_name = context.get("stage", "stage1")
    results = AggregatedResult(test=f"{stage_name}.booster_2_1", code=0)
    
    # Booster might have different ADC phases or RSD names, 
    # but for now we follow the same pattern as in steps.py
    steps = [
        ("ADC (Baseline)", ADCResultChecker()),
        ("RSD1 ON", RSDController()),
        ("ADC (RSD1)", ADCResultChecker()),
        ("RSD1+2 ON", RSDController()),
        ("ADC (RSD1_2)", ADCResultChecker()),
        ("RSD All OFF", RSDController()),
        ("Mesh Configurator", MeshConfigurator()),
    ]
    
    return run_steps_sequentially(steps, context, logger, results)
