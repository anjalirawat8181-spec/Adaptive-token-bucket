
import math

RENORMALIZE_UNAVAILABLE_INDICATORS = True


def classify_indicator(value):
    if value <= 0.35:
        return "low"
    elif value <= 0.75:
        return "medium"
    return "high"


def calculate_load(
    cpu,
    memory,
    resources,
    renormalize_unavailable=RENORMALIZE_UNAVAILABLE_INDICATORS,
):
    indicators = {
        "cpu": cpu,
        "memory": memory,
        "resources": resources,
    }

    available = {
        name: value
        for name, value in indicators.items()
        if value is not None
    }
    for value in available.values():
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Indicators must be in [0, 1]")

    states = {
        name: classify_indicator(value) if value is not None else None
        for name, value in indicators.items()
    }
    if not available:
        return {
            "load": None,
            "states": states,
            "weights": [],
        }

    ranked = sorted(
        available.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    high_count = sum(
        state == "high" for state in states.values()
    )
    medium_count = sum(
        state == "medium" for state in states.values()
    )

    # Paper case 1 applies when all three indicators occupy one interval.
    all_same_interval = (
        len(available) == 3
        and len(set(states.values())) == 1
    )
    # Assign weights to the highest-impact indicators.
    if all_same_interval:
        weights = [0.50, 0.30, 0.20]
    elif high_count >= 2:
        weights = [0.50, 0.47, 0.03]
    elif high_count == 1:
        weights = [0.90, 0.07, 0.03]
    elif medium_count >= 2:
        weights = [0.50, 0.40, 0.10]
    elif medium_count == 1:
        weights = [0.70, 0.20, 0.10]
    else:
        weights = [0.50, 0.30, 0.20]

    weights = weights[:len(ranked)]
    if renormalize_unavailable:
        weight_total = sum(weights)
        weights = [weight / weight_total for weight in weights]
    ordered_values = [value for _, value in ranked]

    load = sum(
        weight * value
        for weight, value in zip(weights, ordered_values)
    )

    return {
        "load": load,
        "states": states,
        "weights": weights,
    }


def load_rank(load):
    if load <= 0.35:
        return 0
    elif load <= 0.50:
        return 1
    elif load <= 0.75:
        return 2
    elif load <= 0.90:
        return 3
    return 4
