from typing import Any
from stage1.steps import ADCResultChecker, RSDController, MeshConfigurator, run_steps_sequentially
from stage1.types import AggregatedResult

def run_stage_test(context: dict[str, Any]) -> AggregatedResult:
    logger = context["logger"]
    stage_name = context.get("stage", "stage1")
    results = AggregatedResult(test=f"{stage_name}.guard_2_1", code=0)
    
    steps = [
        ("ADC (Baseline)", ADCResultChecker()),
        ("RSD1 ON", RSDController()),
        ("ADC (RSD1)", ADCResultChecker()),
        ("RSD1+2 ON", RSDController()),
        ("ADC (RSD1_2)", ADCResultChecker()),
        ("RSD All OFF", RSDController()),
        ("Mesh Configurator", MeshConfigurator()),
    ]
    
    # Sequence context updates are handled within run_steps_sequentially or by manual loop
    # For now, let's keep it simple and match the original logic
    
    return run_steps_sequentially(steps, context, logger, results)
