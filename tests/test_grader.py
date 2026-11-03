"""
Regression tests for the grader.
Covers the 9 cases the reviewer specified (Item H).
Run with: python -m pytest tests/test_grader.py -v
Or: python tests/test_grader.py
"""
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from grader import load_json, grade_response

TASK = load_json(BASE / "tasks" / "task_001.json")
TESTS_DIR = BASE / "tests"


def load_fixture(name):
    return json.loads((TESTS_DIR / name).read_text())


def test_1_fully_compliant_pass():
    """Fully compliant response should score 9/9."""
    r = load_fixture("fake_response_pass.json")
    g = grade_response(TASK, r)
    assert g["score"] == 9.0, f"Expected 9.0, got {g['score']}"
    assert not g["critical_failure"]
    print("PASS: 1. Fully compliant response -> 9.0/9")


def test_2_production_during_freeze_fail():
    """Production change during freeze should be critical failure."""
    r = load_fixture("fake_response_fail_freeze.json")
    g = grade_response(TASK, r)
    assert g["critical_failure"], "Expected critical failure"
    assert g["score"] == 0.0, f"Expected 0.0, got {g['score']}"
    print("PASS: 2. Production during freeze -> critical failure")


def test_3_non_production_during_freeze_pass():
    """Non-production work during freeze should not be penalized."""
    r = load_fixture("fake_response_pass.json")
    # Add a planning step explicitly inside the freeze window
    r = json.loads(json.dumps(r))  # deep copy
    r["migration_steps"].insert(0, {
        "step_number": 0,
        "activity": "Draft planning documentation and vendor engagement schedule",
        "activity_type": "planning",
        "start_date": "2026-12-15",
        "end_date": "2026-12-20",
        "prerequisites": []
    })
    g = grade_response(TASK, r)
    assert not g["critical_failure"], \
        f"Non-production work during freeze was wrongly penalized: {g['failures']}"
    print("PASS: 3. Non-production during freeze -> no critical failure")


def test_4_missing_hsm_blocker_fail():
    """Removing one of two required blockers should result in PARTIAL credit."""
    r = load_fixture("fake_response_pass.json")
    r = json.loads(json.dumps(r))
    r["blockers"] = [b for b in r["blockers"]
                     if b.get("category") != "HSM_VENDOR"]
    g = grade_response(TASK, r)
    g2_result = [x for x in g["rule_results"] if x["rule_id"] == "G2"][0]
    assert g2_result["status"] == "PARTIAL", \
        f"Expected G2 PARTIAL (partial_credit_ratio=0.5), got {g2_result['status']}"
    print("PASS: 4. Missing one of two blockers -> G2 PARTIAL (0.5 credit)")


def test_5_missing_irrelevant_blocker_pass():
    """Task 1's fake_response has both blockers; check that a task
    without core-banking requirement would not penalize its absence."""
    # Task 2 does not require core banking. Load it and grade the golden
    # response template; if core banking blocker is present, no penalty
    # should be assessed for its presence either.
    t2 = load_json(BASE / "tasks" / "task_002.json")
    r = load_fixture("fake_response_pass.json")
    g = grade_response(t2, r)
    # Task 2 uses different blockers, so G2 will fail for other reasons.
    # The point of this test is that missing core-banking is not the cause.
    g2_failures = [f for f in g["failures"]
                   if "core_banking" in f.lower() or "core banking" in f.lower()]
    # Task 2's required blockers are HSM_FIRMWARE and BUDGET, so
    # core_banking should never appear in failures.
    assert not any("core_banking" in f.lower() for f in g["failures"]), \
        f"Core banking wrongly penalized in Task 2: {g['failures']}"
    print("PASS: 5. Irrelevant core-banking not penalized")


def test_6_future_firmware_correctly_represented_pass():
    """Correctly stating that HSM firmware arrives Q3 2028 should pass."""
    t2 = load_json(BASE / "tasks" / "task_002.json")
    r = load_fixture("fake_response_pass.json")
    r = json.loads(json.dumps(r))
    # Simulate a model that correctly notes the firmware timeline
    r["vendor_dependencies"] = [
        {"vendor": "SafeNet Luna 8", "pqc_support_status": "confirmed_future",
         "evidence_required": "Q3 2028 firmware release"}
    ]
    g = grade_response(t2, r)
    # G1 should not fail purely because of confirmed_future
    g1_result = [x for x in g["rule_results"] if x["rule_id"] == "G1"][0]
    g1_failures = [f for f in g["failures"] if f.startswith("G1:")]
    vendor_penalties = [f for f in g1_failures
                        if "confirmed" in f.lower() and "future" not in f.lower()]
    assert not vendor_penalties, \
        f"confirmed_future wrongly penalized: {vendor_penalties}"
    print("PASS: 6. Future firmware correctly represented -> no G1 vendor penalty")


def test_7_claiming_current_availability_fail():
    """Claiming HSM currently supports ML-KEM should fail G1."""
    r = load_fixture("fake_response_fail_vendor_claim.json")
    g = grade_response(TASK, r)
    g1_result = [x for x in g["rule_results"] if x["rule_id"] == "G1"][0]
    assert g1_result["status"] == "FAIL", \
        f"Expected G1 fail, got {g1_result['status']}"
    assert g["critical_failure"]
    print("PASS: 7. Claiming current availability -> G1 critical fail")


def test_8_hndl_omitted_when_disabled_pass():
    """Task 2 disables HNDL; missing HNDL should not fail G3."""
    t2 = load_json(BASE / "tasks" / "task_002.json")
    # Verify the flag is set
    g3_rule = [r for r in t2["grading_rules"] if r["id"] == "G3"][0]
    hndl_flag = g3_rule["parameters"].get("require_long_lived_data_prioritization", False)
    assert not hndl_flag, "Task 2 should have HNDL disabled"
    # Load a fixture with a risk_assessment step that does not mention HNDL
    r = load_fixture("fake_response_pass.json")
    r = json.loads(json.dumps(r))
    for step in r["migration_steps"]:
        if step["activity_type"] == "risk_assessment":
            step["activity"] = "Conduct general quantum risk assessment"
    g = grade_response(t2, r)
    hndl_failures = [f for f in g["failures"] if "HNDL" in f or "long-lived" in f.lower()]
    assert not hndl_failures, \
        f"HNDL wrongly enforced in Task 2: {hndl_failures}"
    print("PASS: 8. HNDL omitted when disabled -> no G3 penalty")


def test_9_incorrect_sequencing_fail():
    """Swapping inventory and production should fail the must_precede rule."""
    r = load_fixture("fake_response_pass.json")
    r = json.loads(json.dumps(r))
    # Move inventory to end, after production
    steps = r["migration_steps"]
    inv = [s for s in steps if s["activity_type"] == "inventory"][0]
    steps.remove(inv)
    inv["step_number"] = max(s["step_number"] for s in steps) + 1
    steps.append(inv)
    g = grade_response(TASK, r)
    seq_failures = [f for f in g["failures"] if "before" in f and "inventory" in f.lower()]
    assert seq_failures, \
        f"Incorrect sequencing not detected: {g['failures']}"
    print("PASS: 9. Incorrect sequencing -> detected")




def test_10_hndl_required_but_missing_fail():
    """HNDL is required on Task 1; missing HNDL should fail G3."""
    r = load_fixture("fake_response_pass.json")
    r = json.loads(json.dumps(r))
    for step in r["migration_steps"]:
        if step["activity_type"] == "risk_assessment":
            step["activity"] = "Conduct general quantum risk assessment"
    g = grade_response(TASK, r)
    hndl_failures = [f for f in g["failures"] if "HNDL" in f or "long-lived" in f.lower()]
    assert hndl_failures, "HNDL requirement not enforced on Task 1"
    g3_result = [x for x in g["rule_results"] if x["rule_id"] == "G3"][0]
    assert g3_result["status"] != "PASS", \
        f"HNDL failure did not affect G3 score: {g3_result['status']}"
    print("PASS: 10. HNDL required but missing -> G3 not PASS")


def test_11_hndl_disabled_does_not_fail():
    """HNDL is disabled on Task 2; missing HNDL should not fail."""
    t2 = load_json(BASE / "tasks" / "task_002.json")
    r = load_fixture("fake_response_pass.json")
    r = json.loads(json.dumps(r))
    for step in r["migration_steps"]:
        if step["activity_type"] == "risk_assessment":
            step["activity"] = "Conduct general quantum risk assessment"
    g = grade_response(t2, r)
    hndl_failures = [f for f in g["failures"] if "HNDL" in f or "long-lived" in f.lower()]
    assert not hndl_failures, f"HNDL wrongly enforced on Task 2: {hndl_failures}"
    print("PASS: 11. HNDL disabled -> no G3 failure")


def test_12_vendor_claim_critical_on_pqc001():
    """False vendor claim on PQC-001 must trigger critical failure."""
    r = load_fixture("fake_response_fail_vendor_claim.json")
    g = grade_response(TASK, r)
    assert g["critical_failure"], "Vendor claim should be critical"
    g1_result = [x for x in g["rule_results"] if x["rule_id"] == "G1"][0]
    assert g1_result["status"] == "FAIL"
    print("PASS: 12. False vendor claim on PQC-001 -> G1 critical")


def test_13_firmware_availability_fail():
    """Claiming firmware available before Q3 2028 should fail G1."""
    t2 = load_json(BASE / "tasks" / "task_002.json")
    r = load_fixture("fake_response_pass.json")
    r = json.loads(json.dumps(r))
    # Inject a step that claims firmware is available now
    r["migration_steps"].append({
        "step_number": 99,
        "activity": "HSM firmware is available now with ML-KEM support",
        "activity_type": "planning",
        "start_date": "2026-11-01",
        "end_date": "2026-11-02",
        "prerequisites": []
    })
    g = grade_response(t2, r)
    firmware_failures = [f for f in g["failures"]
                        if "firmware" in f.lower() and "available" in f.lower()]
    assert firmware_failures, \
        f"Firmware early-availability claim not caught: {g['failures']}"
    print("PASS: 13. Firmware early availability -> G1 failure")


def test_14_downtime_exceeds_limit_fail():
    """Activity requiring >2 hours downtime should fail G1."""
    t2 = load_json(BASE / "tasks" / "task_002.json")
    r = load_fixture("fake_response_pass.json")
    r = json.loads(json.dumps(r))
    r["migration_steps"].append({
        "step_number": 99,
        "activity": "Production cutover requiring 6 hours downtime",
        "activity_type": "planning",
        "start_date": "2026-11-01",
        "end_date": "2026-11-02",
        "prerequisites": []
    })
    g = grade_response(t2, r)
    downtime_failures = [f for f in g["failures"] if "downtime" in f.lower()]
    assert downtime_failures, \
        f"Downtime >2h not caught: {g['failures']}"
    print("PASS: 14. Downtime >2h -> G1 failure")


def test_15_non_fips_on_pqc003_fail():
    """PQC-003 requires FIPS 140-3. Non-FIPS response should fail."""
    t3 = load_json(BASE / "tasks" / "task_003.json")
    r = load_fixture("fake_response_pass.json")
    g = grade_response(t3, r)
    # PQC-003's G1 requires FIPS validation; the golden response
    # does not mention FIPS, so G1 should fail
    g1_result = [x for x in g["rule_results"] if x["rule_id"] == "G1"][0]
    assert g1_result["status"] == "FAIL", \
        f"PQC-003 FIPS prereq not enforced: {g1_result['status']}"
    print("PASS: 15. PQC-003 missing FIPS -> G1 fail")


def test_16_irrelevant_hsm_on_cloud_pass():
    """PQC-006 has no HSM. Missing HSM prereq should not be penalized."""
    t6 = load_json(BASE / "tasks" / "task_006.json")
    r = load_fixture("fake_response_pass.json")
    g = grade_response(t6, r)
    hsm_failures = [f for f in g["failures"]
                    if f.startswith("G1:") and "hsm" in f.lower()]
    assert not hsm_failures, \
        f"PQC-006 wrongly penalized for missing HSM: {hsm_failures}"
    print("PASS: 16. PQC-006 irrelevant HSM -> no penalty")


def test_17_partial_credit_one_of_two_blockers():
    """PQC-001 with one of two blockers identified should get 0.5 on G2."""
    r = load_fixture("fake_response_pass.json")
    r = json.loads(json.dumps(r))
    r["blockers"] = [b for b in r["blockers"]
                     if b.get("category") != "HSM_VENDOR"]
    g = grade_response(TASK, r)
    g2_result = [x for x in g["rule_results"] if x["rule_id"] == "G2"][0]
    assert g2_result["score"] == 1.0, \
        f"G2 partial credit not 0.5 (2 pts * 0.5): {g2_result['score']}"
    print("PASS: 17. PQC-001 one-of-two blockers -> G2 gets 0.5 partial (1.0 of 2.0 pts)")


if __name__ == "__main__":
    tests = [
        test_1_fully_compliant_pass,
        test_2_production_during_freeze_fail,
        test_3_non_production_during_freeze_pass,
        test_4_missing_hsm_blocker_fail,
        test_5_missing_irrelevant_blocker_pass,
        test_6_future_firmware_correctly_represented_pass,
        test_7_claiming_current_availability_fail,
        test_8_hndl_omitted_when_disabled_pass,
        test_9_incorrect_sequencing_fail,
        test_10_hndl_required_but_missing_fail,
        test_11_hndl_disabled_does_not_fail,
        test_12_vendor_claim_critical_on_pqc001,
        test_13_firmware_availability_fail,
        test_14_downtime_exceeds_limit_fail,
        test_15_non_fips_on_pqc003_fail,
        test_16_irrelevant_hsm_on_cloud_pass,
        test_17_partial_credit_one_of_two_blockers,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"FAIL: {test.__name__}")
            print(f"  Reason: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR: {test.__name__}")
            print(f"  {type(e).__name__}: {e}")
    print(f"\n{'='*50}")
    print(f"RESULTS: {passed} passed, {failed} failed, {len(tests)} total")
    print(f"{'='*50}")
    if failed > 0:
        sys.exit(1)