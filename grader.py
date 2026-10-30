import json
import re
from pathlib import Path
from datetime import date


BASE_DIR = Path(__file__).resolve().parent
TASK_PATH = BASE_DIR / "tasks" / "task_001.json"
RESPONSE_PATH = BASE_DIR / "tests" / "fake_response_pass.json"

# Fixed reference date makes model comparisons reproducible. Override this in
# the G3 rule parameters with planning_reference_date when evaluating another
# scenario or a different assessment date.
DEFAULT_PLANNING_REFERENCE_DATE = date(2026, 10, 30)


# ============================================================
# GENERAL UTILITIES
# ============================================================

def load_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def norm(value):
    if isinstance(value, list):
        value = " ".join(str(item) for item in value)
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def parse_date(value):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def get_planning_reference_date(params):
    """Use an explicit task reference date, otherwise the evaluation date."""
    configured = parse_date(params.get("planning_reference_date"))
    return configured or DEFAULT_PLANNING_REFERENCE_DATE


def parse_money_amounts(value):
    """Extract monetary amounts from schema-permitted string assumptions."""
    if not isinstance(value, str):
        return []
    # Supports USD 50,000, $50,000, USD 50000 and similar formats.
    matches = re.findall(
        r"(?:(?:USD|US\$|\$)\s*)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        value,
        flags=re.IGNORECASE
    )
    amounts = []
    for match in matches:
        try:
            amounts.append(float(match.replace(",", "")))
        except ValueError:
            continue
    return amounts


def weight_points(weight):
    return {
        "critical": 4,
        "high": 2,
        "medium": 1,
        "low": 0.5
    }.get(norm(weight), 0)


def rule_parameters(rule):
    return rule.get("parameters", rule.get("params", {}))


def contains_any(text, terms):
    text = norm(text)
    return any(norm(term) in text for term in terms if norm(term))


def get_rule_id(rule):
    return rule.get("id", rule.get("rule_id", "UNKNOWN"))


# ============================================================
# G1: HARD CONSTRAINTS
# ============================================================

def evaluate_g1(params, response):
    failures = []
    successes = []

    freeze_start = parse_date(params.get("freeze_start"))
    freeze_end = parse_date(params.get("freeze_end"))

    if not freeze_start or not freeze_end:
        return 0, ["G1: Invalid freeze dates in task configuration."], []

    prohibited_types = {
        norm(item) for item in params.get("prohibited_activity_types", [])
    }

    steps = response.get("migration_steps", [])
    if not isinstance(steps, list):
        return 0, ["G1: migration_steps must be a list."], []

    production_steps = []

    for step in steps:
        if not isinstance(step, dict):
            failures.append("G1: A migration step is not a valid object.")
            continue

        activity = norm(step.get("activity"))
        activity_type = norm(step.get("activity_type"))

        if activity_type == "production_crypto_change":
            production_steps.append(step)

        is_prohibited = activity_type in prohibited_types

        # Detect explicitly prohibited work even if the activity_type is wrong.
        prohibited_phrases = (
            "production crypto replacement",
            "production cryptographic change",
            "production cryptographic replacement",
            "hsm firmware upgrade",
            "major application deployment",
            "production pqc deployment"
        )
        if any(phrase in activity for phrase in prohibited_phrases):
            is_prohibited = True

        if not is_prohibited:
            continue

        start = parse_date(step.get("start_date"))
        end = parse_date(step.get("end_date"))

        if not start or not end:
            failures.append(
                f"G1: Prohibited activity '{activity[:100]}' has missing "
                "or invalid dates."
            )
            continue

        if start > end:
            failures.append(
                f"G1: Prohibited activity '{activity[:100]}' has an invalid date range."
            )
            continue

        # The task explicitly makes 15 January inclusive.
        if start <= freeze_end and end >= freeze_start:
            failures.append(
                f"G1: Prohibited activity '{activity[:100]}' overlaps "
                "the production change freeze."
            )

    # The scenario says both vendors remain unconfirmed unless written
    # evidence is supplied. This response schema has no evidence-verification
    # field, so a "confirmed" status is treated as an unsupported claim.
    dependencies = response.get("vendor_dependencies", [])
    if isinstance(dependencies, list):
        for vendor in dependencies:
            if not isinstance(vendor, dict):
                continue
            vendor_name = norm(vendor.get("vendor"))
            status = norm(vendor.get("pqc_support_status"))
            if status in {
                "confirmed", "supported", "available", "compatible",
                "pqc-ready", "pqc ready"
            }:
                failures.append(
                    f"G1: Vendor '{vendor_name}' is incorrectly presented "
                    "as having confirmed PQC support."
                )

    # Narrow text checks: only explicit vendor + PQC-support assertions.
    positive_claim_patterns = [
        r"\b(?:thales(?:\s+luna(?:\s+network)?\s+hsm(?:\s+7)?)?|"
        r"luna(?:\s+network)?\s+hsm(?:\s+7)?|hsm)\s+"
        r"(?:currently\s+)?supports?\s+(?:ml-kem|ml-dsa|pqc)\b",
        r"\b(?:thales(?:\s+luna(?:\s+network)?\s+hsm(?:\s+7)?)?|"
        r"luna(?:\s+network)?\s+hsm(?:\s+7)?|hsm)\s+"
        r"has confirmed support for\s+(?:ml-kem|ml-dsa|pqc)\b",
        r"\b(?:ml-kem|ml-dsa|pqc)\s+(?:is|are)\s+"
        r"supported by\s+(?:thales|luna|the hsm)\b",
        r"\b(?:third-party\s+)?core banking platform\s+"
        r"(?:currently\s+)?supports?\s+(?:ml-kem|ml-dsa|pqc)\b",
        r"\b(?:core banking|platform) vendor\s+"
        r"(?:currently\s+)?supports?\s+(?:ml-kem|ml-dsa|pqc)\b",
        r"\b(?:ml-kem|ml-dsa|pqc)\s+(?:is|are)\s+"
        r"supported by\s+(?:the core banking vendor|the platform vendor)\b"
    ]

    for step in steps:
        if not isinstance(step, dict):
            continue
        activity = norm(step.get("activity"))
        for pattern in positive_claim_patterns:
            if re.search(pattern, activity, re.IGNORECASE):
                failures.append(
                    "G1: Possible unsupported vendor-readiness claim in "
                    f"activity: '{activity[:120]}'."
                )
                break

    # Production migration must follow laboratory validation and name the
    # required external approvals/compatibility confirmations.
    for step in production_steps:
        prerequisites = norm(step.get("prerequisites", []))
        prior_lab_steps = [
            item for item in steps
            if isinstance(item, dict)
            and norm(item.get("activity_type")) == "lab_testing"
            and parse_date(item.get("end_date"))
            and parse_date(step.get("start_date"))
            and parse_date(item.get("end_date")) < parse_date(step.get("start_date"))
        ]

        if not prior_lab_steps:
            failures.append(
                "G1: Production cryptographic change is scheduled without "
                "a completed earlier laboratory-testing activity."
            )

        required_prerequisite_concepts = [
            ("completed lab testing",
             ("lab", "testing")),
            ("written HSM compatibility confirmation",
             ("written", "hsm", "compatibility confirmation")),
            ("written core banking compatibility confirmation",
             ("written", "core banking", "compatibility confirmation")),
            ("security validation",
             ("security", "validation")),
            ("formal approval",
             ("approval",))
        ]

        for label, terms in required_prerequisite_concepts:
            if not all(term in prerequisites for term in terms):
                failures.append(
                    f"G1: Production migration prerequisites do not clearly "
                    f"include {label}."
                )

    if failures:
        return 0, failures, successes

    successes.append(
        "G1: Freeze constraints, vendor-status constraints, and production "
        "migration prerequisites are satisfied."
    )
    return 1, failures, successes


# ============================================================
# G2: BLOCKER COVERAGE
# ============================================================

def evaluate_g2(params, response):
    failures = []
    successes = []

    blockers = response.get("blockers", [])
    if not isinstance(blockers, list):
        return 0, ["G2: blockers must be a list."], []

    required = params.get("required_blockers", [])
    if not isinstance(required, list) or not required:
        return 0, ["G2: Task has no valid required_blockers list."], []

    identified = 0

    for requirement in required:
        if not isinstance(requirement, dict):
            continue

        required_id = norm(requirement.get("id"))
        required_category = norm(requirement.get("category"))
        accepted_terms = requirement.get("accepted_terms", [])
        required_context = requirement.get("required_context", [])
        resolution_terms = requirement.get("resolution_required", [])

        matched = False

        for blocker in blockers:
            if not isinstance(blocker, dict):
                continue

            category = norm(blocker.get("category"))
            blocker_id = norm(blocker.get("blocker_id"))
            description = norm(blocker.get("blocker"))
            reason = norm(blocker.get("reason"))
            resolution = norm(blocker.get("resolution_required"))

            # Category is the strongest deterministic identifier. Also
            # permit a matching blocker_id or accepted phrase.
            category_match = category == required_category
            id_match = blocker_id == required_id
            accepted_match = contains_any(
                " ".join([description, reason, resolution, category]),
                accepted_terms
            )

            if not (category_match or id_match or accepted_match):
                continue

            # Require a substantive explanation, not merely a label.
            reason_ok = (
                params.get("require_blocker_reason", True) is False
                or len(reason.split()) >= 8
            )

            # Check the technical context using equivalent phrases.
            context_text = " ".join([description, reason, resolution])
            context_hits = 0

            for term in required_context:
                term = norm(term)

                if term == "pqc compatibility":
                    hit = contains_any(context_text, [
                        "pqc compatibility", "pqc", "post-quantum",
                        "ml-kem", "ml-dsa"
                    ])
                elif term == "ml-kem support":
                    hit = "ml-kem" in context_text
                elif term == "ml-dsa support":
                    hit = "ml-dsa" in context_text
                elif term == "firmware compatibility":
                    hit = "firmware" in context_text
                elif term == "vendor confirmation":
                    hit = contains_any(context_text, [
                        "vendor confirmation", "written confirmation",
                        "written thales confirmation", "vendor has not confirmed"
                    ])
                elif term == "migration roadmap":
                    hit = "migration roadmap" in context_text or "roadmap" in context_text
                elif term == "software support":
                    hit = contains_any(context_text, [
                        "software support", "supported software",
                        "supported software versions", "software versions"
                    ])
                else:
                    hit = term in context_text

                if hit:
                    context_hits += 1

            # Most listed context items should be evidenced. Allow one
            # equivalent/context item to be absent where the wording differs.
            context_ok = (
                context_hits >= max(1, len(required_context) - 1)
            )

            # Validate the requested resolution using phrase equivalents.
            resolution_hits = 0
            for term in resolution_terms:
                term = norm(term)

                if "written vendor confirmation" in term:
                    hit = "written" in resolution and "confirmation" in resolution
                elif "supported firmware and software versions" in term:
                    hit = (
                        "firmware" in resolution
                        and "software" in resolution
                        and ("version" in resolution or "versions" in resolution)
                    )
                elif "production compatibility information" in term:
                    hit = (
                        "compatibility" in resolution
                        and contains_any(resolution, ["production", "deployment", "implementation"])
                    )
                elif "implementation and delivery timeline" in term:
                    hit = (
                        contains_any(resolution, ["implementation", "deployment", "upgrade"])
                        and contains_any(resolution, ["timeline", "delivery", "schedule", "date"])
                    )
                elif "written compatibility confirmation" in term:
                    hit = "written" in resolution and "confirmation" in resolution
                elif "vendor migration roadmap" in term:
                    hit = "roadmap" in resolution
                elif "supported implementation options" in term:
                    hit = (
                        contains_any(resolution, ["supported", "supportable", "approved"])
                        and contains_any(resolution, ["implementation", "deployment", "integration", "option"])
                    )
                elif "integration and testing requirements" in term:
                    hit = (
                        contains_any(resolution, ["integration", "interface", "interoperability"])
                        and contains_any(resolution, ["testing", "test", "validation"])
                    )
                else:
                    hit = term in resolution

                if hit:
                    resolution_hits += 1

            resolution_ok = (
                resolution_hits == len(resolution_terms)
                if resolution_terms else True
            )

            if reason_ok and context_ok and resolution_ok:
                matched = True
                break

        if matched:
            identified += 1
            successes.append(
                f"G2: Required blocker '{required_id}' is correctly identified "
                "with its reason and resolution."
            )
        else:
            failures.append(
                f"G2: Required blocker '{required_id}' is missing or "
                "does not sufficiently explain its context and resolution."
            )

    if identified == len(required):
        return 1, failures, successes
    if identified == 1 and len(required) >= 2:
        return 0.5, failures, successes
    return 0, failures, successes


# ============================================================
# G3: SEQUENCE, ALGORITHMS, AND LONG-LIVED DATA
# ============================================================

def evaluate_g3(params, response):
    failures = []
    successes = []

    steps = response.get("migration_steps", [])
    if not isinstance(steps, list) or not steps:
        return 0, ["G3: migration_steps are missing or invalid."], []

    valid_steps = [step for step in steps if isinstance(step, dict)]
    categories = [
        {
            "category": norm(step.get("activity_type")),
            "activity": norm(step.get("activity")),
            "step_number": step.get("step_number")
        }
        for step in valid_steps
    ]

    # Reject stale or internally inconsistent schedules. A task may pin a
    # planning_reference_date in its rule parameters for reproducible runs;
    # otherwise the grader uses the date on which it is executed.
    reference_date = get_planning_reference_date(params)
    stale_steps = []
    invalid_ranges = []
    for step in valid_steps:
        start = parse_date(step.get("start_date"))
        end = parse_date(step.get("end_date"))
        label = norm(step.get("activity_type")) or norm(step.get("activity")) or "unnamed activity"
        if start and start < reference_date:
            stale_steps.append(label)
        if start and end and start > end:
            invalid_ranges.append(label)

    if stale_steps:
        failures.append(
            "G3: One or more migration activities are scheduled before the "
            f"planning reference date ({reference_date.isoformat()}): "
            + ", ".join(sorted(set(stale_steps))[:5]) + "."
        )
    else:
        successes.append(
            f"G3: Migration schedule does not begin before the planning "
            f"reference date ({reference_date.isoformat()})."
        )

    if invalid_ranges:
        failures.append(
            "G3: One or more migration activities have start dates after "
            "their end dates: " + ", ".join(sorted(set(invalid_ranges))[:5]) + "."
        )

    # A migration plan must include an actual production phase, not stop at
    # testing or at drafting a future plan.
    production_positions = [
        index for index, item in enumerate(categories)
        if item["category"] == "production_crypto_change"
        or "production crypto change" in item["activity"]
        or "production cryptographic change" in item["activity"]
        or "production pqc migration" in item["activity"]
    ]
    production_step_exists = bool(production_positions)
    if not production_step_exists:
        failures.append(
            "G3: An explicit production_crypto_change activity is missing; "
            "the plan must schedule production migration after validation."
        )

    # Required activity categories.
    required_categories = params.get("required_activity_categories", [])
    category_passes = 0

    for required in required_categories:
        required = norm(required)
        if any(
            required == item["category"]
            or required.replace("_", " ") in item["activity"]
            for item in categories
        ):
            category_passes += 1
        else:
            failures.append(
                f"G3: Required activity category '{required}' is missing."
            )

    # Step numbers must be present, unique, and ordered.
    numbers = [item["step_number"] for item in categories]
    numbering_ok = (
        all(isinstance(number, int) for number in numbers)
        and len(set(numbers)) == len(numbers)
        and numbers == sorted(numbers)
    )

    if numbering_ok:
        successes.append("G3: Migration step numbering is valid.")
    else:
        failures.append(
            "G3: Migration steps must have unique, ordered integer step numbers."
        )

    # Sequence relationships.
    relationships = params.get("must_precede", [])
    order_passes = 0

    for relationship in relationships:
        before = norm(relationship.get("before"))
        after = norm(relationship.get("after"))

        before_positions = [
            index for index, item in enumerate(categories)
            if item["category"] == before
            or before.replace("_", " ") in item["activity"]
        ]
        after_positions = [
            index for index, item in enumerate(categories)
            if item["category"] == after
            or after.replace("_", " ") in item["activity"]
        ]

        valid = (
            bool(before_positions)
            and bool(after_positions)
            and min(before_positions) < min(after_positions)
        )

        if valid:
            order_passes += 1
        else:
            failures.append(
                f"G3: Required order '{before}' before '{after}' is not satisfied."
            )

    if order_passes == len(relationships):
        successes.append("G3: Required migration sequence is satisfied.")

    # Production must be later than risk assessment, vendor engagement and
    # lab testing, even if a task configuration omits one of these relations.
    if production_step_exists:
        prod_index = min(production_positions)
        for required_prior in ("risk_assessment", "vendor_engagement", "lab_testing"):
            prior_indices = [
                index for index, item in enumerate(categories)
                if item["category"] == required_prior
                or required_prior.replace("_", " ") in item["activity"]
            ]
            if not prior_indices or min(prior_indices) >= prod_index:
                failures.append(
                    f"G3: Production migration must occur after a completed "
                    f"'{required_prior}' activity."
                )

    # Algorithm roles: accept either the task's canonical role -> algorithm
    # representation or the response's algorithm -> human-readable role form.
    required_algorithms = params.get("required_algorithms", {})
    response_roles = response.get("algorithm_roles", {})

    algorithm_ok = True

    for required_role, required_algorithm in required_algorithms.items():
        role = norm(required_role)
        algorithm = norm(required_algorithm)

        direct_value = response_roles.get(required_role)
        direct_ok = norm(direct_value) == algorithm

        reverse_ok = False
        for response_algorithm, response_role in response_roles.items():
            if norm(response_algorithm) == algorithm:
                role_text = norm(response_role)

                if role == "key_encapsulation":
                    reverse_ok = contains_any(role_text, [
                        "key establishment", "key encapsulation", "key exchange"
                    ])
                elif role == "digital_signature":
                    reverse_ok = contains_any(role_text, [
                        "digital signature", "digital signatures", "signature"
                    ])
                else:
                    reverse_ok = role.replace("_", " ") in role_text

                if reverse_ok:
                    break

        if not (direct_ok or reverse_ok):
            algorithm_ok = False
            failures.append(
                f"G3: Incorrect or missing algorithm role '{required_role}'. "
                f"Expected {required_algorithm}."
            )

    if algorithm_ok:
        successes.append(
            "G3: ML-KEM is assigned to key establishment and ML-DSA "
            "is assigned to digital signatures."
        )

    # Long-lived sensitive data/HNDL prioritisation in risk assessment.
    risk_steps = [
        step for step in valid_steps
        if norm(step.get("activity_type")) == "risk_assessment"
    ]

    risk_text = " ".join(norm(step.get("activity")) for step in risk_steps)

    long_lived_terms = [
        "long-lived", "long lived", "10-15 years", "10–15 years",
        "10 to 15 years", "10–15", "harvest-now-decrypt-later",
        "harvest now decrypt later", "hndl"
    ]

    long_lived_ok = (
        bool(risk_steps)
        and contains_any(risk_text, long_lived_terms)
        and contains_any(risk_text, [
            "sensitive information", "sensitive data",
            "confidential information", "customer information"
        ])
    )

    if long_lived_ok:
        successes.append(
            "G3: Risk assessment explicitly prioritises long-lived "
            "sensitive information and HNDL exposure."
        )
    else:
        failures.append(
            "G3: Risk assessment does not sufficiently prioritise "
            "long-lived sensitive data and HNDL exposure."
        )

    # Follow the task's deterministic scoring bands.
    all_sequence_checks = (
        category_passes == len(required_categories)
        and order_passes == len(relationships)
        and numbering_ok
        and production_step_exists
        and not stale_steps
        and not invalid_ranges
    )

    if all_sequence_checks and algorithm_ok and long_lived_ok:
        return 1, failures, successes

    # Partial credit is appropriate for some errors, but not for a
    # fundamentally incorrect algorithm-role assignment.
    if not algorithm_ok:
        return 0, failures, successes

    if category_passes > 0 and (order_passes > 0 or numbering_ok):
        return 0.5, failures, successes

    return 0, failures, successes


# ============================================================
# G4: BUDGET COMPLIANCE
# ============================================================

def evaluate_g4(params, response):
    failures = []
    successes = []

    budget = response.get("budget", {})
    if not isinstance(budget, dict):
        return 0, ["G4: budget must be an object."], []

    maximum = params.get("maximum_budget_usd", 250000)
    estimate = budget.get("estimated_total_usd")

    if not isinstance(estimate, (int, float)) or isinstance(estimate, bool):
        return 0, ["G4: estimated_total_usd must be numeric."], []

    if estimate < 0:
        return 0, ["G4: Estimated budget cannot be negative."], []

    if estimate > maximum:
        return 0, [
            f"G4: Estimated budget ${estimate:,.2f} exceeds "
            f"the approved ${maximum:,.2f} limit."
        ], []

    within_budget_value = budget.get("within_budget")
    within_budget_ok = (
        within_budget_value is True
        or (isinstance(within_budget_value, str)
            and within_budget_value.strip().lower() == "true")
    )
    if not within_budget_ok:
        return 0, [
            "G4: within_budget must explicitly be true (boolean true or string \"true\")."
        ], []

    assumptions = budget.get("cost_assumptions", [])
    if not isinstance(assumptions, list) or not assumptions:
        return 0.5, [
            "G4: Cost assumptions are missing."
        ], []

    numeric_amounts = []

    for item in assumptions:
        if isinstance(item, dict):
            amount = item.get(
                "estimated_cost_usd",
                item.get("amount_usd", item.get("cost_usd", item.get("amount")))
            )
            if isinstance(amount, (int, float)) and not isinstance(amount, bool):
                numeric_amounts.append(float(amount))
            elif isinstance(amount, str):
                numeric_amounts.extend(parse_money_amounts(amount))
        elif isinstance(item, str):
            numeric_amounts.extend(parse_money_amounts(item))

    if not numeric_amounts:
        return 0.5, [
            "G4: Cost assumptions do not contain a verifiable numeric breakdown."
        ], []

    breakdown_total = sum(numeric_amounts)

    if abs(breakdown_total - float(estimate)) > 1:
        return 0.5, [
            f"G4: Cost breakdown totals ${breakdown_total:,.2f}, "
            f"but estimated_total_usd is ${estimate:,.2f}."
        ], []

    successes.append(
        f"G4: The ${estimate:,.2f} estimate is within the "
        f"${maximum:,.2f} limit and the numeric cost breakdown reconciles."
    )
    return 1, failures, successes


# ============================================================
# GRADING ENGINE
# ============================================================

def grade_response(task, response):
    rules = task.get("grading_rules", [])

    max_score = sum(weight_points(rule.get("weight", "low")) for rule in rules)
    total_score = 0.0
    results = []
    all_failures = []
    all_successes = []
    critical_failure = False

    evaluators = {
        "hard_constraint": evaluate_g1,
        "blocker_coverage": evaluate_g2,
        "sequence_order": evaluate_g3,
        "budget_compliance": evaluate_g4
    }

    for rule in rules:
        rule_id = get_rule_id(rule)
        rule_type = norm(rule.get("type"))
        points = weight_points(rule.get("weight", "low"))
        params = rule_parameters(rule)

        evaluator = evaluators.get(rule_type)

        if evaluator is None:
            results.append({
                "rule_id": rule_id,
                "score": 0,
                "max_score": points,
                "status": "ERROR"
            })
            all_failures.append(
                f"{rule_id}: Unknown grading rule type '{rule_type}'."
            )
            continue

        score_fraction, failures, successes = evaluator(params, response)
        earned = score_fraction * points

        total_score += earned
        all_failures.extend(failures)
        all_successes.extend(successes)

        status = (
            "PASS" if score_fraction == 1
            else "PARTIAL" if score_fraction > 0
            else "FAIL"
        )

        results.append({
            "rule_id": rule_id,
            "score": round(earned, 2),
            "max_score": points,
            "status": status
        })

        if rule_type == "hard_constraint" and score_fraction == 0:
            critical_failure = True

    if critical_failure:
        total_score = 0.0

    percentage = (total_score / max_score * 100) if max_score else 0

    return {
        "score": round(total_score, 2),
        "max_score": round(max_score, 2),
        "percentage": round(percentage, 2),
        "critical_failure": critical_failure,
        "rule_results": results,
        "successes": all_successes,
        "failures": all_failures
    }


# ============================================================
# COMMAND-LINE ENTRY POINT
# ============================================================

def main():
    try:
        task = load_json(TASK_PATH)
        response = load_json(RESPONSE_PATH)
    except FileNotFoundError as exc:
        print(f"ERROR: Required file not found: {exc}")
        print("Expected files:")
        print(f"  Task:     {TASK_PATH}")
        print(f"  Response: {RESPONSE_PATH}")
        return
    except json.JSONDecodeError as exc:
        print(f"ERROR: Invalid JSON: {exc}")
        return

    result = grade_response(task, response)

    print("\n========================================")
    print(" PQC MIGRATION EVALUATION RESULTS")
    print("========================================")
    print(f"\nScore: {result['score']} / {result['max_score']}")
    print(f"Percentage: {result['percentage']}%")
    print(f"Critical failure: {result['critical_failure']}")

    print("\nRULE-BY-RULE RESULTS")
    for item in result["rule_results"]:
        print(
            f"{item['rule_id']}: {item['status']} "
            f"({item['score']} / {item['max_score']})"
        )

    if result["successes"]:
        print("\nSUCCESSES")
        for message in result["successes"]:
            print(f"[PASS] {message}")

    if result["failures"]:
        print("\nFAILURES AND WARNINGS")
        for message in result["failures"]:
            print(f"[FAIL] {message}")

    print("\n========================================")


if __name__ == "__main__":
    main()
