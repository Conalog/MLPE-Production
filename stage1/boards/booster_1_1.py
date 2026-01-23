from typing import Any
from stage1.steps import ADCResultChecker, RSDController, MeshConfigurator, run_steps_sequentially
from stage1.types import AggregatedResult

def run_stage_test(context: dict[str, Any]) -> AggregatedResult:
    logger = context["logger"]
    stage_name = context.get("stage", "stage1")
    results = AggregatedResult(test=f"{stage_name}.booster_1_1", code=0)
    
    steps = [
        ("ADC (Baseline)", ADCResultChecker()),
        ("RSD2 ON", RSDController()),
        ("ADC (RSD2)", ADCResultChecker()),
        ("RSD All OFF", RSDController()),
        ("Mesh Configurator", MeshConfigurator()),
    ]
    
    return run_steps_sequentially(steps, context, logger, results)
