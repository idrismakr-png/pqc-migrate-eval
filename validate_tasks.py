"""Validates every task JSON against the schema. Item J."""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
TASKS = BASE / "tasks"

REQUIRED_TOP = ["task_id", "difficulty", "scenario", "question",
                "expected_output_schema", "grading_rules", "expert_notes"]
REQUIRED_RULES = {"G1", "G2", "G3", "G4"}
VALID_WEIGHTS = {"critical", "high", "medium", "low"}
VALID_DIFFICULTY = {"conventional", "constrained", "adversarial"}


def validate_task(path):
    errors = []
    try:
        task = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f"Invalid JSON: {e}"]

    for field in REQUIRED_TOP:
        if field not in task:
            errors.append(f"Missing required field: {field}")

    if task.get("difficulty") not in VALID_DIFFICULTY:
        errors.append(f"Invalid difficulty: {task.get('difficulty')}")

    rules = task.get("grading_rules", [])
    rule_ids = {r.get("id") for r in rules}
    missing = REQUIRED_RULES - rule_ids
    if missing:
        errors.append(f"Missing grading rules: {missing}")

    total_weight = 0
    for r in rules:
        rid = r.get("id", "?")
        w = r.get("weight")
        if w not in VALID_WEIGHTS:
            errors.append(f"{rid}: invalid weight '{w}'")
        total_weight += {"critical": 4, "high": 2, "medium": 1, "low": 0.5}.get(w, 0)

    # Verify total = 9
    if total_weight != 9:
        errors.append(f"Total weight is {total_weight}, expected 9")

    # Verify G1 has freeze dates
    g1 = next((r for r in rules if r.get("id") == "G1"), None)
    if g1:
        p = g1.get("parameters", {})
        if not p.get("freeze_start") or not p.get("freeze_end"):
            errors.append("G1 missing freeze_start or freeze_end")

    # Verify G3 has required_algorithms
    g3 = next((r for r in rules if r.get("id") == "G3"), None)
    if g3:
        p = g3.get("parameters", {})
        if not p.get("required_algorithms"):
            errors.append("G3 missing required_algorithms")

    return errors


def main():
    task_files = sorted(TASKS.glob("task_*.json"))
    if not task_files:
        print("No tasks found")
        sys.exit(1)

    total_errors = 0
    for tf in task_files:
        errors = validate_task(tf)
        if errors:
            total_errors += len(errors)
            print(f"FAIL: {tf.name}")
            for e in errors:
                print(f"  - {e}")
        else:
            print(f"PASS: {tf.name}")

    print(f"\n{'='*50}")
    print(f"{len(task_files)} tasks, {total_errors} errors")
    print(f"{'='*50}")
    sys.exit(0 if total_errors == 0 else 1)


if __name__ == "__main__":
    main()