import json
from pathlib import Path
import copy

BASE = Path(__file__).resolve().parent
TESTS = BASE / "tests"
TESTS.mkdir(exist_ok=True)

# Load the golden response as the base template
golden = json.loads((TESTS / "fake_response_pass.json").read_text())

def save(name, data):
    (TESTS / name).write_text(json.dumps(data, indent=2))
    print(f"  wrote {name}")

print("Generating negative fixtures...")

# ------------------------------------------------------------
# 1. Change-freeze violator: production change during freeze
# ------------------------------------------------------------
d = copy.deepcopy(golden)
d["migration_steps"].append({
    "step_number": 6,
    "activity": "Production deployment of ML-KEM for TLS endpoints",
    "activity_type": "production_crypto_change",
    "start_date": "2026-12-15",
    "end_date": "2026-12-20",
    "prerequisites": ["lab testing", "hsm compatibility confirmation"]
})
save("fake_response_fail_freeze.json", d)

# ------------------------------------------------------------
# 2. Hallucinated vendor readiness
# ------------------------------------------------------------
d = copy.deepcopy(golden)
for v in d["vendor_dependencies"]:
    v["pqc_support_status"] = "confirmed"
save("fake_response_fail_vendor_claim.json", d)

# ------------------------------------------------------------
# 3. Budget overrun
# ------------------------------------------------------------
d = copy.deepcopy(golden)
d["budget"]["estimated_total_usd"] = 350000
d["budget"]["within_budget"] = True
d["budget"]["cost_assumptions"] = [
    {"category": "Everything", "estimated_cost_usd": 350000}
]
save("fake_response_fail_budget.json", d)

# ------------------------------------------------------------
# 4. Missing core-banking blocker
# ------------------------------------------------------------
d = copy.deepcopy(golden)
d["blockers"] = [b for b in d["blockers"] if b["category"] != "CORE_BANKING_VENDOR"]
save("fake_response_fail_missing_blocker.json", d)

# ------------------------------------------------------------
# 5. Swapped algorithm roles
# ------------------------------------------------------------
d = copy.deepcopy(golden)
d["algorithm_roles"] = {
    "ML-KEM": "Digital signatures",
    "ML-DSA": "Key establishment"
}
save("fake_response_fail_algo_swap.json", d)

print("Done.")