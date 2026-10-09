
def service_rate(load, idle_capacity, max_load=1.0):
    load = min(max(load, 0.0), max_load)

    return max(
        0.0,
        (1.0 - load / max_load) * idle_capacity,
    )


def expected_arrival_rate(mean_tasks, service_rate_value):
    if mean_tasks < 0:
        raise ValueError("Mean tasks cannot be negative")

    if service_rate_value <= 0:
        return 0.0

    return (
        mean_tasks * service_rate_value
        / (1.0 + mean_tasks)
    )


def traffic_intensity(arrival_rate, service_rate_value):
    if service_rate_value <= 0:
        return float("inf")

    return arrival_rate / service_rate_value
