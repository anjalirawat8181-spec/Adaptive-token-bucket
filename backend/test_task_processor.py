
from tasks.task_processor import Task, TaskProcessor

# Create a processor with 8 worker threads
processor = TaskProcessor(workers=8)

# Submit 20 tasks
futures = []

for i in range(20):
    task = Task(
        task_id=i + 1,
        task_type="simple",
        duration_ms=5,
    )
    future = processor.submit(task)
    futures.append(future)

# Wait for all 20 tasks to finish
results = [future.result(timeout=10) for future in futures]

# Verify the results
print("Tasks submitted:", len(futures))
print("Tasks completed:", len(results))

assert len(results) == 20, "Not all tasks completed!"

for result in results:
    assert result["queue_wait_ms"] >= 0, (
        f"Negative queue wait: {result}"
    )
    assert result["latency_ms"] >= 0, (
        f"Negative latency: {result}"
    )

print("All queue waiting times are non-negative.")
print("All latencies are non-negative.")
print("TEST PASSED!")
