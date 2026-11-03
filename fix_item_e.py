import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
TASKS = BASE / "tasks"

# Tasks that distinguish confirmed_now vs confirmed_future.
# Update their expected_output_schema and vendor-status vocab.
UPDATED_SCHEMA = "confirmed_current | confirmed_future | unconfirmed | unsupported"

for tf in sorted(TASKS.glob("task_*.json")):
    task = json.loads(tf.read_text())
    tid = task.get("task_id", "")
    changed = False

    # 1. Update schema
    schema = task.get("expected_output_schema", {})
    vd = schema.get("vendor_dependencies", [])
    if isinstance(vd, list) and vd and isinstance(vd[0], dict):
        if "pqc_support_status" in vd[0]:
            vd[0]["pqc_support_status"] = UPDATED_SCHEMA
            changed = True

    # 2. Ensure G1 vendor enforcement recognizes both current and future
    for rule in task.get("grading_rules", []):
        if rule.get("id") == "G1":
            p = rule.setdefault("parameters", {})
            # Add a "requires_current" flag only for tasks where the vendor
            # has confirmed future support and must not be falsely rejected
            if tid in {"PQC-002", "PQC-003", "PQC-006"}:
                p["allow_future_vendor_support"] = True
                changed = True

    if changed:
        tf.write_text(json.dumps(task, indent=2))
        print(f"OK: {tf.name} schema + vendor flags updated")
    else:
        print(f"SKIP: {tf.name} unchanged")

print("\nItem E fix complete.")