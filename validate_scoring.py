"""Validates scoring consistency across all tasks. Item I."""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
TASKS = BASE / "tasks"
WEIGHTS = {"critical": 4, "high": 2, "medium": 1, "low": 0.5}


def main():
    errors = []
    for tf in sorted(TASKS.glob("task_*.json")):
        task = json.loads(tf.read_text())
        rules = task.get("grading_rules", [])
        tid = task.get("task_id", tf.stem)

        # Check total = 9
        total = sum(WEIGHTS.get(r.get("weight"), 0) for r in rules)
        if total != 9:
            errors.append(f"{tid}: total weight {total} != 9")

        # Exactly one critical rule
        criticals = [r for r in rules if r.get("weight") == "critical"]
        if len(criticals) != 1:
            errors.append(f"{tid}: {len(criticals)} critical rules (expected 1)")

        # Critical rule must be G1
        if criticals and criticals[0].get("id") != "G1":
            errors.append(f"{tid}: critical rule is {criticals[0].get('id')}, expected G1")

        # G4 budget_limit must match G1 budget_limit
        g1 = next((r for r in rules if r.get("id") == "G1"), None)
        g4 = next((r for r in rules if r.get("id") == "G4"), None)
        if g1 and g4:
            g1_limit = g1["parameters"].get("budget_limit_usd")
            g4_limit = g4["parameters"].get("maximum_budget_usd")
            if g1_limit is not None and g4_limit is not None and g1_limit != g4_limit:
                errors.append(f"{tid}: G1 budget ${g1_limit} != G4 budget ${g4_limit}")

    if errors:
        print("FAIL:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print(f"PASS: all {len(list(TASKS.glob('task_*.json')))} tasks have consistent scoring")
        sys.exit(0)


if __name__ == "__main__":
    main()