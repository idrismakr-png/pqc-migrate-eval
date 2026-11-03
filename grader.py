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

# Grader version for reproducibility metadata
GRADER_VERSION = "3.0.0"


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

        # Classification is based only on activity_type. Text is not
        # inspected for prohibited actions, avoiding false positives.
        if activity_type not in prohibited_types:
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

        if start <= freeze_end and end >= freeze_start:
            failures.append(
                f"G1: Prohibited activity '{activity[:100]}' overlaps "
                "the production change freeze."
            )

    # Vendor-status check (opt-in, defaults to False).
    enforce_vendors = (
        params.get("enforce_unconfirmed_vendors", False)
        or params.get("vendor_support_must_remain_unconfirmed_without_written_evidence", False)
    )
    if enforce_vendors:
        dependencies = response.get("vendor_dependencies", [])
        if isinstance(dependencies, list):
            for vendor in dependencies:
                if not isinstance(vendor, dict):
                    continue
                vendor_name = norm(vendor.get("vendor"))
                status = norm(vendor.get("pqc_support_status"))
                # Distinguish current confirmation from future commitment.
                if status in {"confirmed", "supported", "available", "compatible",
                              "pqc-ready", "pqc ready"}:
                    failures.append(
                        f"G1: Vendor '{vendor_name}' is incorrectly presented "
                        "as having confirmed PQC support."
                    )
                elif status in {"confirmed_future", "planned", "projected"}:
                    # Future commitments are acceptable if the timeline
                    # is clearly stated as not-yet-available, OR if the
                    # task explicitly allows future vendor support.
                    if not params.get("allow_future_vendor_support", False):
                        failures.append(
                            f"G1: Vendor '{vendor_name}' presented as confirmed "
                            "future support but the task requires current confirmation."
                        )

    # Lab-before-production check (opt-in, defaults to False).
    if params.get("enforce_lab_before_production", False):
        for step in production_steps:
            start = parse_date(step.get("start_date"))
            prior_lab_steps = [
                item for item in steps
                if isinstance(item, dict)
                and norm(item.get("activity_type")) == "lab_testing"
                and parse_date(item.get("end_date"))
                and start
                and parse_date(item.get("end_date")) < start
            ]
            if not prior_lab_steps:
                failures.append(
                    "G1: Production cryptographic change is scheduled without "
                    "a completed earlier laboratory-testing activity."
                )

    # Required prerequisites from the task (per-task only).
    required_prerequisite_concepts = params.get(
        "required_prerequisite_concepts", []
    )
    for step in production_steps:
        prerequisites = norm(step.get("prerequisites", []))
        for label, terms in required_prerequisite_concepts:
            if not all(term in prerequisites for term in terms):
                failures.append(
                    f"G1: Production migration prerequisites do not clearly "
                    f"include {label}."
                )

    # Enforce task-defined failure_conditions (Defect 2).
    failure_conditions = params.get("failure_conditions", [])
    max_hours_limit = params.get("max_downtime_hours")

    # Firmware early-availability check (any claim firmware is available now)
    if any("firmware" in c.lower() and "available" in c.lower()
           for c in failure_conditions):
        firmware_now_pattern = re.compile(
            r"firmware\s+(?:is\s+|will\s+be\s+)?"
            r"(available|released|shipping|supported)\s+"
            r"(now|immediately|currently|today|in\s+2026|in\s+2027)",
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
            for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:hours|hrs|hour|hr|h)\b", text):
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
                break

    failures = list(dict.fromkeys(failures))

    if failures:
        return 0, failures, successes

    successes.append(
        "G1: Freeze constraints, vendor-status constraints, and production "
        "migration prerequisites are satisfied."
    )
    return 1, failures, successes



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
    # Partial credit if task configured (Defect 5)
    partial_ratio = params.get("partial_credit_ratio")
    if partial_ratio is not None and identified > 0:
        return float(partial_ratio), failures, successes
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
            "step_number": step.get("step_number"),
        }
        for step in valid_steps
    ]

    # Stale-date detection.
    reference_date = get_planning_reference_date(params)
    stale = []
    bad_range = []
    for step in valid_steps:
        s = parse_date(step.get("start_date"))
        e = parse_date(step.get("end_date"))
        label = norm(step.get("activity_type")) or norm(step.get("activity")) or "activity"
        if s and s < reference_date:
            stale.append(label)
        if s and e and s > e:
            bad_range.append(label)

    if stale:
        failures.append(
            "G3: Activities scheduled before the planning reference date "
            f"({reference_date.isoformat()}): "
            + ", ".join(sorted(set(stale))[:5]) + "."
        )
    else:
        successes.append(
            f"G3: Schedule does not begin before {reference_date.isoformat()}."
        )

    if bad_range:
        failures.append(
            "G3: Activities have start dates after end dates: "
            + ", ".join(sorted(set(bad_range))[:5]) + "."
        )

    # Required activity categories.
    required_categories = params.get("required_activity_categories", [])
    category_passes = 0
    for required in required_categories:
        r = norm(required)
        if any(r == item["category"] or r.replace("_", " ") in item["activity"]
               for item in categories):
            category_passes += 1
        else:
            failures.append(f"G3: Required activity category '{required}' is missing.")

    # Numbering.
    numbers = [item["step_number"] for item in categories]
    numbering_ok = (
        all(isinstance(n, int) and not isinstance(n, bool) for n in numbers)
        and len(set(numbers)) == len(numbers)
        and numbers == sorted(numbers)
    )
    if not numbering_ok:
        failures.append("G3: Migration steps must have unique, ordered integer step numbers.")

    # must_precede relationships (task-driven only).
    relationships = params.get("must_precede", [])
    order_passes = 0
    for relationship in relationships:
        before = norm(relationship.get("before"))
        after = norm(relationship.get("after"))
        before_pos = [
            i for i, item in enumerate(categories)
            if item["category"] == before or before.replace("_", " ") in item["activity"]
        ]
        after_pos = [
            i for i, item in enumerate(categories)
            if item["category"] == after or after.replace("_", " ") in item["activity"]
        ]
        if before_pos and after_pos and min(before_pos) < min(after_pos):
            order_passes += 1
        else:
            failures.append(f"G3: Required order '{before}' before '{after}' is not satisfied.")

    # Algorithm roles.
    required_algorithms = params.get("required_algorithms", {})
    response_roles = response.get("algorithm_roles", {})
    algorithm_ok = True
    for required_role, required_algorithm in required_algorithms.items():
        role = norm(required_role)
        algorithm = norm(required_algorithm)
        direct = response_roles.get(required_role)
        direct_ok = norm(direct) == algorithm
        reverse_ok = False
        for resp_alg, resp_role in response_roles.items():
            if norm(resp_alg) == algorithm:
                role_text = norm(resp_role)
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

    # Long-lived data / HNDL (opt-in only).
    long_lived_ok = True
    if params.get("require_long_lived_data_prioritization", False):
        risk_steps = [
            step for step in valid_steps
            if norm(step.get("activity_type")) == "risk_assessment"
        ]
        risk_text = " ".join(norm(step.get("activity")) for step in risk_steps)
        long_lived_terms = [
            "long-lived", "long lived", "10-15 years", "10–15 years",
            "10 to 15 years", "harvest-now-decrypt-later",
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
        if not long_lived_ok:
            failures.append(
                "G3: Risk assessment does not sufficiently prioritise "
                "long-lived sensitive data and HNDL exposure."
            )

    # Opt-in sequencing enforcement (defaults to False).
    if params.get("enforce_production_after_validation", False):
        production_pos = [
            i for i, item in enumerate(categories)
            if item["category"] == "production_crypto_change"
        ]
        if production_pos:
            prod_idx = min(production_pos)
            for required_prior in ("risk_assessment", "vendor_engagement", "lab_testing"):
                prior = [
                    i for i, item in enumerate(categories)
                    if item["category"] == required_prior
                ]
                if not prior or min(prior) >= prod_idx:
                    failures.append(
                        f"G3: Production must occur after a completed "
                        f"'{required_prior}' activity."
                    )

    # Scoring.
    all_checks = (
        category_passes == len(required_categories)
        and order_passes == len(relationships)
        and numbering_ok
        and not stale
        and not bad_range
        and long_lived_ok
    )
    if all_checks and algorithm_ok:
        return 1, failures, successes
    if not algorithm_ok:
        return 0, failures, successes
    if category_passes > 0 and (order_passes > 0 or numbering_ok):
        return 0.5, failures, successes
    return 0, failures, successes



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
