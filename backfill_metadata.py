import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
RESULTS = BASE / "results"
TASKS = BASE / "tasks"

# Import grader version
import sys
sys.path.insert(0, str(BASE))
from grader import GRADER_VERSION

for result_file in sorted(RESULTS.glob("deepseek-chat_PQC-*.json")):
    result = json.loads(result_file.read_text())
    
    # Skip if already has metadata
    if result.get("grader_version") == GRADER_VERSION:
        print(f"SKIP: {result_file.name} already has metadata")
        continue
    
    task_id = result.get("task_id")
    if not task_id:
        print(f"SKIP: {result_file.name} has no task_id")
        continue
    
    # Find the task file
    task_file = None
    for tf in TASKS.glob("task_*.json"):
        t = json.loads(tf.read_text())
        if t.get("task_id") == task_id:
            task_file = tf
            break
    
    if not task_file:
        print(f"SKIP: {result_file.name} - task {task_id} not found")
        continue
    
    # Compute hashes
    task_file_hash = hashlib.sha256(task_file.read_bytes()).hexdigest()[:16]
    
    # Recompute prompt hash from task
    from run_eval import build_prompt
    task = json.loads(task_file.read_text())
    prompt = build_prompt(task)
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    
    # Add metadata to existing result
    result["grader_version"] = GRADER_VERSION
    result["prompt_hash"] = prompt_hash
    result["task_file_hash"] = task_file_hash
    
    result_file.write_text(json.dumps(result, indent=2))
    print(f"OK: {result_file.name}")

print("\nDone. All existing results backfilled with metadata.")