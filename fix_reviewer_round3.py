"""
Fixes 7 defects from reviewer round 3.
- Defect 1: HNDL failure now affects G3 score
- Defect 2: failure_conditions now enforced in G1
- Defect 3: vendor enforcement key mismatch resolved
- Defect 4: irrelevant prerequisites in PQC-003 to 008 corrected
- Defect 5: G2 partial credit restored (task-configurable)
- Defect 6: .env.example and check_env.py unified on DeepSeek
- Defect 7: summary status computed correctly
"""
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent
GRADER = BASE / "grader.py"
RUNNER = BASE / "run_eval.py"
TASKS = BASE / "tasks"

# ============================================================
# DEFECT 1: HNDL failure affects G3 score
# ============================================================
gs = GRADER.read_text()

old_all_checks = '''    all_checks = (
        category_passes == len(required_categories)
        and order_passes == len(relationships)
        and numbering_ok
        and not stale
        and not bad_range
    )'''
new_all_checks = '''    all_checks = (
        category_passes == len(required_categories)
        and order_passes == len(relationships)
        and numbering_ok
        and not stale
        and not bad_range
        and long_lived_ok
    )'''
assert old_all_checks in gs, "G3 all_checks block not found"
gs = gs.replace(old_all_checks, new_all_checks, 1)

# Ensure long_lived_ok exists even when opt-in is off
if "long_lived_ok = True" not in gs:
    gs = gs.replace(
        '    if params.get("require_long_lived_data_prioritization", False):',
        '    long_lived_ok = True\n    if params.get("require_long_lived_data_prioritization", False):',
        1
    )

print("OK: Defect 1 - HNDL failure affects G3 score")

# ============================================================
# DEFECT 2: failure_conditions enforced in G1
# ============================================================
# Append enforcement before "failures = list(dict.fromkeys(failures))"
old_dedup = '''    failures = list(dict.fromkeys(failures))

    if failures:
        return 0, failures, successes

    successes.append(
        "G1: Freeze constraints, vendor-status constraints, and production "
        "migration prerequisites are satisfied."
    )'''
new_dedup = '''    # Enforce task-defined failure_conditions (Defect 2).
    failure_conditions = params.get("failure_conditions", [])
    for condition in failure_conditions:
        cond_lower = condition.lower()
        # Firmware availability claim check
        if "firmware" in cond_lower and "available" in cond_lower:
            firmware_early_claim = re.compile(
                r"firmware.{0,80}(available|released|shipping).{0,20}(2026|2027)",
                re.IGNORECASE,
            )
            for step in steps:
                if isinstance(step, dict):
                    text = norm(step.get("activity"))
                    if firmware_early_claim.search(text):
                        failures.append(
                            f"G1: Firmware claimed available before "
                            f"expected release: {condition}"
                        )
                        break
        # Downtime limit check
        if "downtime" in cond_lower and "exceed" in cond_lower:
            max_hours = params.get("max_downtime_hours")
            if max_hours:
                for step in steps:
                    if not isinstance(step, dict):
                        continue
                    text = norm(step.get("activity"))
                    m = re.search(r"(\\d+(?:\\.\\d+)?)\\s*(?:hours|hrs|h)", text)
                    if m and float(m.group(1)) > max_hours:
                        failures.append(
                            f"G1: Activity exceeds {max_hours}h downtime: "
                            f"{text[:100]}"
                        )
                        break

    failures = list(dict.fromkeys(failures))

    if failures:
        return 0, failures, successes

    successes.append(
        "G1: Freeze constraints, vendor-status constraints, and production "
        "migration prerequisites are satisfied."
    )'''
assert old_dedup in gs, "G1 dedup block not found"
gs = gs.replace(old_dedup, new_dedup, 1)

print("OK: Defect 2 - failure_conditions enforced in G1")

# ============================================================
# DEFECT 3: Vendor key mismatch - accept both keys
# ============================================================
old_vendor_check = '''    if params.get("enforce_unconfirmed_vendors", False):'''
new_vendor_check = '''    enforce_vendors = (
        params.get("enforce_unconfirmed_vendors", False)
        or params.get("vendor_support_must_remain_unconfirmed_without_written_evidence", False)
    )
    if enforce_vendors:'''
assert old_vendor_check in gs, "Vendor enforcement key not found"
gs = gs.replace(old_vendor_check, new_vendor_check, 1)

print("OK: Defect 3 - vendor key mismatch resolved (accepts both keys)")

GRADER.write_text(gs)

# ============================================================
# DEFECT 5: G2 partial credit restored (task-configurable)
# ============================================================
gs = GRADER.read_text()
old_g2_return = '''    if identified == len(required):
        return 1, failures, successes
    return 0, failures, successes'''
new_g2_return = '''    if identified == len(required):
        return 1, failures, successes
    # Partial credit if task configured (Defect 5)
    partial_ratio = params.get("partial_credit_ratio")
    if partial_ratio is not None and identified > 0:
        return float(partial_ratio), failures, successes
    return 0, failures, successes'''
assert old_g2_return in gs, "G2 return block not found"
gs = gs.replace(old_g2_return, new_g2_return, 1)
GRADER.write_text(gs)
print("OK: Defect 5 - G2 partial credit restored (task-configurable)")

# ============================================================
# DEFECT 4: Fix irrelevant prerequisites in PQC-003..008
# ============================================================
# Correct prerequisite lists per task
TASK_PREREQS = {
    "PQC-003": [  # EHR, FIPS
        ["completed lab testing", ["lab", "testing"]],
        ["FIPS 140-3 validation", ["fips", "140"]],
        ["EHR vendor certification", ["ehr", "certification"]],
        ["security validation", ["security", "validation"]],
    ],
    "PQC-004": [  # Cisco + Microsoft
        ["completed lab testing", ["lab", "testing"]],
        ["Cisco firmware compatibility confirmation", ["cisco", "firmware"]],
        ["Microsoft Exchange PQC plugin confirmation", ["microsoft", "exchange"]],
        ["security validation", ["security", "validation"]],
    ],
    "PQC-005": [  # Ransomware recovery
        ["completed lab testing", ["lab", "testing"]],
        ["NIST algorithm approval", ["nist", "approval"]],
        ["security validation", ["security", "validation"]],
    ],
    "PQC-006": [  # Cloud SaaS, AWS KMS
        ["completed lab testing", ["lab", "testing"]],
        ["AWS KMS PQC compatibility", ["aws", "kms"]],
        ["security validation", ["security", "validation"]],
    ],
    "PQC-007": [  # DoD VPN
        ["completed lab testing", ["lab", "testing"]],
        ["DoD NIST algorithm approval", ["dod", "nist"]],
        ["VPN appliance PQC compatibility", ["vpn", "appliance"]],
        ["security validation", ["security", "validation"]],
    ],
    "PQC-008": [  # Embedded IoT
        ["completed lab testing", ["lab", "testing"]],
        ["device memory constraint validation", ["memory", "constraint"]],
        ["AWS KMS PQC compatibility", ["aws", "kms"]],
        ["security validation", ["security", "validation"]],
    ],
}

for tf in sorted(TASKS.glob("task_*.json")):
    task = json.loads(tf.read_text())
    tid = task.get("task_id")
    if tid not in TASK_PREREQS:
        continue
    for rule in task["grading_rules"]:
        if rule.get("id") == "G1":
            rule["parameters"]["required_prerequisite_concepts"] = TASK_PREREQS[tid]
    tf.write_text(json.dumps(task, indent=2))
    print(f"OK: Defect 4 - {tid} prerequisites updated")

# Ensure PQC-002 has vendor enforcement enabled
t2_file = TASKS / "task_002.json"
t2 = json.loads(t2_file.read_text())
for rule in t2["grading_rules"]:
    if rule.get("id") == "G1":
        rule["parameters"]["enforce_unconfirmed_vendors"] = True
t2_file.write_text(json.dumps(t2, indent=2))
print("OK: PQC-002 vendor enforcement enabled")

# Enable G2 partial credit in PQC-001 per its original scoring config
t1_file = TASKS / "task_001.json"
t1 = json.loads(t1_file.read_text())
for rule in t1["grading_rules"]:
    if rule.get("id") == "G2":
        rule["parameters"]["partial_credit_ratio"] = 0.5
t1_file.write_text(json.dumps(t1, indent=2))
print("OK: PQC-001 G2 partial credit ratio set to 0.5")

# ============================================================
# DEFECT 6: .env.example and check_env.py unified on DeepSeek
# ============================================================
env_example = BASE / ".env.example"
env_example.write_text("DEEPSEEK_API_KEY=your_deepseek_api_key_here\n")
print("OK: Defect 6a - .env.example updated to DeepSeek")

check_env = BASE / "check_env.py"
check_env.write_text('''import os
import sys
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

api_key = os.getenv("DEEPSEEK_API_KEY")
if not api_key:
    sys.exit("FAIL: DEEPSEEK_API_KEY not found in .env")

print(f"PASS: key loaded (prefix={api_key[:12]}, length={len(api_key)})")
print(f"PASS: python={sys.executable}")

client = OpenAI(
    base_url="https://api.deepseek.com/v1",
    api_key=api_key,
)

try:
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "Reply with exactly: CONNECTION_OK"}],
        max_tokens=10,
        temperature=0,
    )
    content = resp.choices[0].message.content.strip()
    print(f"PASS: DeepSeek responded: {content}")
except Exception as e:
    sys.exit(f"FAIL: DeepSeek call failed: {e}")
''')
print("OK: Defect 6b - check_env.py updated to DeepSeek")

# ============================================================
# DEFECT 7: Summary status computed correctly
# ============================================================
rs = RUNNER.read_text()
old_status = '''    summary_data = {

        "status": "completed",'''
new_status = '''    overall_status = (
        "completed" if len(failed) == 0 else "completed_with_errors"
    )
    summary_data = {

        "status": overall_status,'''
assert old_status in rs, "Summary status block not found"
rs = rs.replace(old_status, new_status, 1)
RUNNER.write_text(rs)
print("OK: Defect 7 - summary status now reflects errors")

print("\nAll 7 defects fixed. Run tests next.")