import re
from pathlib import Path

GRADER = Path(__file__).resolve().parent / "grader.py"
src = GRADER.read_text()

old = '''    # Enforce task-defined failure_conditions (Defect 2).
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
                        break'''

new = '''    # Enforce task-defined failure_conditions (Defect 2).
    failure_conditions = params.get("failure_conditions", [])
    max_hours_limit = params.get("max_downtime_hours")

    # Firmware early-availability check (any claim firmware is available now)
    if any("firmware" in c.lower() and "available" in c.lower()
           for c in failure_conditions):
        firmware_now_pattern = re.compile(
            r"firmware\\s+(?:is\\s+|will\\s+be\\s+)?"
            r"(available|released|shipping|supported)\\s+"
            r"(now|immediately|currently|today|in\\s+2026|in\\s+2027)",
            re.IGNORECASE,
        )
        for step in steps:
            if not isinstance(step, dict):
                continue
            text = norm(step.get("activity"))
            if firmware_now_pattern.search(text):
                failures.append(
                    "G1: Firmware claimed available before expected release"
                )
                break

    # Downtime limit check
    if max_hours_limit is not None:
        for step in steps:
            if not isinstance(step, dict):
                continue
            text = norm(step.get("activity"))
            for m in re.finditer(r"(\\d+(?:\\.\\d+)?)\\s*(?:hours|hrs|hour|hr|h)\\b", text):
                try:
                    hours = float(m.group(1))
                except ValueError:
                    continue
                if hours > max_hours_limit:
                    failures.append(
                        f"G1: Activity exceeds {max_hours_limit}h downtime limit"
                    )
                    break
            if any("downtime limit" in f for f in failures):
                break'''

assert old in src, "Defect 2 v1 block not found"
src = src.replace(old, new, 1)
GRADER.write_text(src)
print("OK: Defect 2 v2 - firmware and downtime checks strengthened")