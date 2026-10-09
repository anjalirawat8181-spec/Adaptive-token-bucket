
def classify_indicator(value):
    if value <= 0.35:
        return "low"
    elif value <= 0.75:
        return "medium"
    return "high"


def calculate_load(cpu, memory, resources):
    indicators = {
        "cpu": cpu,
        "memory": memory,
        "resources": resources,
    }

    for value in indicators.values():
        if not 0 <= value <= 1:
            raise ValueError("Indicators must be in [0, 1]")

    ranked = sorted(
        indicators.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    states = {
        name: classify_indicator(value)
        for name, value in indicators.items()
    }

    high_count = sum(
        state == "high" for state in states.values()
    )
    medium_count = sum(
        state == "medium" for state in states.values()
    )

    # Assign weights to the highest-impact indicators.
    if high_count >= 2:
        weights = [0.50, 0.47, 0.03]
    elif high_count == 1:
        weights = [0.90, 0.07, 0.03]
    elif medium_count >= 2:
        weights = [0.50, 0.40, 0.10]
    elif medium_count == 1:
        weights = [0.70, 0.20, 0.10]
    else:
        weights = [0.50, 0.30, 0.20]

    ordered_values = [
        value for _, value in ranked
    ]

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
