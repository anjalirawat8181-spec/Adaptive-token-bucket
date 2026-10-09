
import random

TASK_COSTS = {
    "simple": 5,
    "general": 20,
    "complex": 80,
}


def generate_tasks(count, task_type="mixed"):
    tasks = []

    for task_id in range(count):
        if task_type == "mixed":
            selected = random.choices(
                ["simple", "general", "complex"],
                weights=[0.5, 0.3, 0.2],
                k=1,
            )[0]
        else:
            selected = task_type

        tasks.append({
            "task_id": task_id + 1,
            "task_type": selected,
            "duration_ms": TASK_COSTS[selected],
        })

    return tasks
