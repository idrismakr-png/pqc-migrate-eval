from pathlib import Path

BASE = Path(__file__).resolve().parent
GRADER = BASE / "grader.py"
RUNNER = BASE / "run_eval.py"

# 1. Add GRADER_VERSION constant to grader.py
gs = GRADER.read_text()
if "GRADER_VERSION" not in gs:
    gs = gs.replace(
        'DEFAULT_PLANNING_REFERENCE_DATE = date(2026, 10, 30)',
        'DEFAULT_PLANNING_REFERENCE_DATE = date(2026, 10, 30)\n\n# Grader version for reproducibility metadata\nGRADER_VERSION = "3.0.0"',
        1
    )
    GRADER.write_text(gs)
    print("OK: GRADER_VERSION added to grader.py")
else:
    print("SKIP: GRADER_VERSION already exists")

# 2. Add metadata fields to run_eval.py output
rs = RUNNER.read_text()

# Update imports
if "from grader import grade_response, GRADER_VERSION" not in rs:
    rs = rs.replace(
        "from grader import grade_response",
        "from grader import grade_response, GRADER_VERSION",
        1
    )
    print("OK: GRADER_VERSION imported in run_eval.py")

# Add hashlib import
if "import hashlib" not in rs:
    rs = rs.replace("import json", "import hashlib\nimport json", 1)
    print("OK: hashlib imported in run_eval.py")

# Add prompt_hash before saving output_data (only if not already present)
if "prompt_hash" not in rs:
    # Insert metadata building right before "output_data = {" assignment
    old = '        structure_check = validate_response_structure(parsed_response)\n        grade_result = grade_response(task, parsed_response)\n\n        output_data = {'
    new = '''        structure_check = validate_response_structure(parsed_response)
        grade_result = grade_response(task, parsed_response)

        # Reproducibility metadata (Item K)
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
        task_file_hash = hashlib.sha256(Path(task_file).read_bytes()).hexdigest()[:16]

        output_data = {
            "grader_version": GRADER_VERSION,
            "prompt_hash": prompt_hash,
            "task_file_hash": task_file_hash,'''
    assert old in rs, "Could not find structure_check block"
    rs = rs.replace(old, new, 1)
    RUNNER.write_text(rs)
    print("OK: metadata fields added to run_eval.py output")
else:
    print("SKIP: prompt_hash already present")