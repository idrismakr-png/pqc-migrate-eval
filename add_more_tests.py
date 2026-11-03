from pathlib import Path

TF = Path(__file__).resolve().parent / "tests" / "test_grader.py"
src = TF.read_text()

# Find the tests list and extend it
old_list = """    tests = [
        test_1_fully_compliant_pass,
        test_2_production_during_freeze_fail,
        test_3_non_production_during_freeze_pass,
        test_4_missing_hsm_blocker_fail,
        test_5_missing_irrelevant_blocker_pass,
        test_6_future_firmware_correctly_represented_pass,
        test_7_claiming_current_availability_fail,
        test_8_hndl_omitted_when_disabled_pass,
        test_9_incorrect_sequencing_fail,
    ]"""

# New test functions to append before main
new_tests = '''

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
    assert g3_result["status"] != "PASS", \\
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
    assert firmware_failures, \\
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
    assert downtime_failures, \\
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
    assert g1_result["status"] == "FAIL", \\
        f"PQC-003 FIPS prereq not enforced: {g1_result['status']}"
    print("PASS: 15. PQC-003 missing FIPS -> G1 fail")


def test_16_irrelevant_hsm_on_cloud_pass():
    """PQC-006 has no HSM. Missing HSM prereq should not be penalized."""
    t6 = load_json(BASE / "tasks" / "task_006.json")
    r = load_fixture("fake_response_pass.json")
    g = grade_response(t6, r)
    hsm_failures = [f for f in g["failures"]
                    if f.startswith("G1:") and "hsm" in f.lower()]
    assert not hsm_failures, \\
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
    assert g2_result["score"] == 1.0, \\
        f"G2 partial credit not 0.5 (2 pts * 0.5): {g2_result['score']}"
    print("PASS: 17. PQC-001 one-of-two blockers -> G2 gets 0.5 partial (1.0 of 2.0 pts)")


'''

# Insert new tests before "if __name__ == '__main__'"
marker = 'if __name__ == "__main__":'
src = src.replace(marker, new_tests + marker, 1)

# Update the test list
new_list = """    tests = [
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
    ]"""

src = src.replace(old_list, new_list, 1)
TF.write_text(src)
print("OK: 8 additional regression tests added (10-17)")