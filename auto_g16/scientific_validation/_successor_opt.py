"""Private pure Opt assessment; never creates a V30 outcome or acceptance."""
from .service import _classify_gaussian_facts
from .models import MinimumValidationClassification as Classification


def assess_opt(envelope, parsed):
    outcome = _classify_gaussian_facts(envelope, parsed, lambda **fields: fields, pure_opt=True)
    facts = parsed.facts
    geometry = outcome.get("selected_geometry_block")
    opt = outcome.get("accepted_optimization_span")
    stationary = outcome.get("accepted_stationary_span")
    positive = (
        outcome["classification"] is Classification.INCOMPLETE
        and outcome["reason_code"] == "incomplete-mode-count"
        and geometry is not None and opt is not None and stationary is not None
        and facts.get("normal_termination_count") == 1
        and facts.get("error_termination_count") == 0
        and facts.get("frequency_count") == 0 and not facts.get("frequency_blocks")
    )
    return geometry if positive else None, {
        "classification": outcome["classification"].value,
        "reason_codes": (outcome["reason_code"],),
        "geometry_disposition": "accepted_opt_geometry" if positive else "rejected_opt_geometry",
        "optimization_spans": () if opt is None else (opt,),
        "stationary_point_spans": () if stationary is None else (stationary,),
    }
