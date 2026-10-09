
import psutil


def get_system_metrics(active_resources=0, total_resources=8):
    cpu = psutil.cpu_percent(interval=0.1) / 100.0

    memory = (
        psutil.virtual_memory().percent / 100.0
    )

    resource_usage = (
        active_resources / total_resources
        if total_resources > 0
        else 0.0
    )

    return {
        "cpu": min(max(cpu, 0.0), 1.0),
        "memory": min(max(memory, 0.0), 1.0),
        "resource_usage": min(
            max(resource_usage, 0.0), 1.0
        ),
    }
