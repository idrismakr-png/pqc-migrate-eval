from pathlib import Path
p = Path(__file__).resolve().parent / "grader.py"
src = p.read_text()

old = '''                elif status in {"confirmed_future", "planned", "projected"}:
                    # Future commitments are acceptable if the timeline is
                    # clearly stated as not-yet-available.
                    pass'''
new = '''                elif status in {"confirmed_future", "planned", "projected"}:
                    # Future commitments are acceptable if the timeline
                    # is clearly stated as not-yet-available, OR if the
                    # task explicitly allows future vendor support.
                    if not params.get("allow_future_vendor_support", False):
                        failures.append(
                            f"G1: Vendor '{vendor_name}' presented as confirmed "
                            "future support but the task requires current confirmation."
                        )'''

assert old in src, "Future vendor block not found"
src = src.replace(old, new, 1)
p.write_text(src)
print("OK: grader updated for allow_future_vendor_support")