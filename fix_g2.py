from pathlib import Path

GRADER = Path(__file__).resolve().parent / "grader.py"
src = GRADER.read_text()

old = '''    if identified == len(required):
        return 1, failures, successes
    if identified == 1 and len(required) >= 2:
        return 0.5, failures, successes
    return 0, failures, successes'''

new = '''    if identified == len(required):
        return 1, failures, successes
    return 0, failures, successes'''

assert old in src, "G2 partial-credit block not found"
src = src.replace(old, new, 1)
GRADER.write_text(src)
print("OK: G2 no longer grants partial credit for missing blockers.")