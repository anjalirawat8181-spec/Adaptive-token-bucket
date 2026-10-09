
from monitoring.system_monitor import get_system_metrics

# Read system metrics
metrics = get_system_metrics(
    active_resources=4,
    total_resources=8,
)

print("System Metrics:")
print(f"CPU Usage: {metrics['cpu'] * 100:.2f}%")
print(f"Memory Usage: {metrics['memory'] * 100:.2f}%")
print(f"Resource Usage: {metrics['resource_usage'] * 100:.2f}%")

# Validate the measurements
assert 0 <= metrics["cpu"] <= 1
assert 0 <= metrics["memory"] <= 1
assert 0 <= metrics["resource_usage"] <= 1

assert metrics["resource_usage"] == 0.5

print("\nTEST PASSED!")
