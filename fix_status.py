from pathlib import Path

p = Path(__file__).resolve().parent / "run_eval.py"
lines = p.read_text().split("\n")

# Line 541 (index 540) should be the summary status
idx = 540
if lines[idx].strip() != '"status": "completed",':
    raise SystemExit(f"Unexpected line {idx+1}: {lines[idx]}")

lines[idx] = '        "status": ("completed" if not failed else "completed_with_errors"),'
p.write_text("\n".join(lines))
print("OK: summary status now reflects errors")