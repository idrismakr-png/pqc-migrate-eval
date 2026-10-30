import os
import json
import re
import time
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
from openai import OpenAI

from grader import grade_response


# ============================================================
# 1. PROJECT CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
TASKS_DIR = BASE_DIR / "tasks"
RESULTS_DIR = BASE_DIR / "results"
SUMMARY_PATH = RESULTS_DIR / "batch_summary.json"

RESULTS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_MODELS = [
    "deepseek-v4-pro",
    "deepseek-flash"
]

TEMPERATURE = float(os.getenv("TEMPERATURE", "0.0"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "8000"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "180"))
DELAY_BETWEEN_MODELS = float(os.getenv("DELAY_BETWEEN_MODELS", "2"))


# ============================================================
# 2. ENVIRONMENT AND API CONFIGURATION
# ============================================================

load_dotenv(BASE_DIR / ".env")

API_KEY = os.getenv("DEEPSEEK_API_KEY")

if not API_KEY:
    raise ValueError(
    "DEEPSEEK_API_KEY not found in .env. "
    "Please add your DeepSeek API key."
    )

client = OpenAI(
    base_url="https://api.deepseek.com/v1",
    api_key=API_KEY,
    timeout=REQUEST_TIMEOUT,
    max_retries=2,
)


# ============================================================
# 3. FILE UTILITIES
# ============================================================

def load_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def safe_filename(value):
    filename = str(value).replace("/", "_")
    filename = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename)
    return filename.strip("._") or "unknown"


def get_output_path(model_id, task_id):
    return RESULTS_DIR / (
        f"{safe_filename(model_id)}_{safe_filename(task_id)}.json"
    )


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def json_safe_usage(response):
    usage = getattr(response, "usage", None)

    if usage is None:
        return None

    if hasattr(usage, "model_dump"):
        return usage.model_dump()

    if isinstance(usage, dict):
        return usage

    return str(usage)


# ============================================================
# 4. MODEL CONFIGURATION
# ============================================================

def get_model_list():
    """
    Override the default model list in .env:

    OPENROUTER_MODELS=provider/model1,provider/model2
    """

    configured_models = os.getenv("OPENROUTER_MODELS", "").strip()

    if configured_models:
        models = [
            model.strip()
            for model in configured_models.split(",")
            if model.strip()
        ]

        if models:
            return models

    return DEFAULT_MODELS


# ============================================================
# 5. RESPONSE STRUCTURE VALIDATION
# ============================================================

def validate_response_structure(response):

    required_fields = [
        "migration_steps",
        "blockers",
        "vendor_dependencies",
        "algorithm_roles",
        "budget",
        "confidence",
    ]

    expected_types = {
        "migration_steps": list,
        "blockers": list,
        "vendor_dependencies": list,
        "algorithm_roles": dict,
        "budget": dict,
        "confidence": str,
    }

    missing_fields = []
    type_errors = []

    if not isinstance(response, dict):
        return {
            "valid": False,
            "missing_fields": required_fields,
            "type_errors": [
                "Top-level JSON response must be an object."
            ],
        }

    for field in required_fields:
        if field not in response:
            missing_fields.append(field)

    for field, expected_type in expected_types.items():

        if field in response:

            if not isinstance(response[field], expected_type):

                type_errors.append(
                    f"{field} should be {expected_type.__name__}, "
                    f"not {type(response[field]).__name__}."
                )

    return {
        "valid": not missing_fields and not type_errors,
        "missing_fields": missing_fields,
        "type_errors": type_errors,
    }


# ============================================================
# 6. PROMPT CONSTRUCTION
# ============================================================

def build_prompt(task):

    """
    Build a task-specific prompt using only the task's scenario,
    question and expected output schema.

    Grading rules and expert notes are intentionally not exposed
    to the evaluated model.
    """

    schema = task.get("expected_output_schema", {})

    prompt = f"""
You are an expert cybersecurity architect specialising in
post-quantum cryptography (PQC) migration planning.

Prepare a technically defensible, practical migration plan
that directly answers the task below.

TASK ID:
{task.get("task_id", "Not specified")}

SCENARIO:
{task.get("scenario", "")}

QUESTION:
{task.get("question", "")}

REQUIRED OUTPUT STRUCTURE:
{json.dumps(schema, indent=2, ensure_ascii=False)}

INSTRUCTIONS:

1. Return exactly one valid JSON object. Do not include Markdown,
   code fences, or explanatory text outside the JSON object.

2. Use the exact top-level field names and data structures
   specified in the required output structure.

3. Respect every constraint stated in the scenario, including
   budget limits, dates, change freezes, downtime limits,
   regulatory requirements, vendor restrictions, staffing limits,
   product capabilities and delivery timelines.

4. Distinguish confirmed capabilities from vendor claims,
   forecasts, assumptions and unconfirmed dependencies.
   Never present an expected future capability as currently
   available or validated.

5. Do not invent vendor confirmations, product capabilities,
   firmware versions, certification status, delivery dates,
   regulatory approvals or technical compatibility.

6. Identify blockers explicitly. Explain why each blocker matters
   and specify concrete evidence or actions needed to resolve it.

7. Distinguish what can realistically be completed in the
   requested timeframe from what must wait for vendor support,
   validation, certification, procurement or other dependencies.

8. Use ML-KEM for post-quantum key establishment and ML-DSA
   for post-quantum digital signatures where relevant.
   Do not interchange their cryptographic roles.

9. Schedule activities in a logical order. Make prerequisites
   explicit. Do not schedule a production change before its
   technical, operational, vendor and regulatory prerequisites
   have been satisfied.

10. Respect all change freezes and operational downtime limits.
    Do not assume that a non-production activity is permitted
    if the scenario prohibits it.

11. Provide a numeric budget estimate and a numeric cost
    breakdown. Ensure the cost assumptions reconcile with
    the estimated total and remain within the stated budget
    unless the scenario explicitly asks for an over-budget
    assessment.

12. Use dates in YYYY-MM-DD format where dates can responsibly
    be determined. Use null where the schema permits it and
    a date cannot responsibly be determined.

13. State a confidence level consistent with unresolved
    dependencies and uncertainty.

Return only the JSON object.
"""

    return prompt.strip()


# ============================================================
# 7. MODEL EVALUATION
# ============================================================

def run_model(model_id, task, task_file):

    task_id = task.get("task_id", Path(task_file).stem)

    output_file = get_output_path(model_id, task_id)

    print(f"\n    Testing {model_id} on {task_id}...")

    start_time = time.time()

    prompt = build_prompt(task)

    try:

        response = client.chat.completions.create(

            model=model_id,

            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a careful cybersecurity architect. "
                        "Follow the task constraints and return valid JSON only."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],

            temperature=TEMPERATURE,

            max_tokens=MAX_TOKENS,

            #response_format={"type": "json_object"},
        )

        elapsed = time.time() - start_time

        choice = response.choices[0]

        content = choice.message.content

        usage = json_safe_usage(response)

        # ----------------------------------------------------
        # CHECK FOR EMPTY RESPONSE
        # ----------------------------------------------------

        if not content or not content.strip():

            output_data = {
                "task_id": task_id,
                "task_file": Path(task_file).name,
                "model": model_id,
                "status": "empty_response",
                "elapsed_seconds": round(elapsed, 2),
                "created_at_utc": utc_now(),
                "finish_reason": choice.finish_reason,
                "usage": usage,
            }

            save_json(output_file, output_data)

            print("    [ERROR] Model returned an empty response.")

            return {
                "task_id": task_id,
                "model": model_id,
                "status": "error",
                "error": "Empty response",
                "result_file": str(output_file),
            }

        # ----------------------------------------------------
        # PARSE JSON RESPONSE
        # ----------------------------------------------------

        try:

            parsed_response = json.loads(content)

        except json.JSONDecodeError as error:

            output_data = {
                "task_id": task_id,
                "task_file": Path(task_file).name,
                "model": model_id,
                "status": "invalid_json",
                "error": str(error),
                "raw_text": content,
                "elapsed_seconds": round(elapsed, 2),
                "created_at_utc": utc_now(),
                "finish_reason": choice.finish_reason,
                "usage": usage,
            }

            save_json(output_file, output_data)

            print(f"    [ERROR] Invalid JSON: {error}")

            return {
                "task_id": task_id,
                "model": model_id,
                "status": "error",
                "error": f"Invalid JSON: {error}",
                "result_file": str(output_file),
            }

        if not isinstance(parsed_response, dict):

            output_data = {
                "task_id": task_id,
                "task_file": Path(task_file).name,
                "model": model_id,
                "status": "invalid_json_structure",
                "error": "Top-level JSON must be an object.",
                "raw_response": parsed_response,
                "elapsed_seconds": round(elapsed, 2),
                "created_at_utc": utc_now(),
                "finish_reason": choice.finish_reason,
                "usage": usage,
            }

            save_json(output_file, output_data)

            print("    [ERROR] Top-level JSON is not an object.")

            return {
                "task_id": task_id,
                "model": model_id,
                "status": "error",
                "error": "Top-level JSON is not an object",
                "result_file": str(output_file),
            }

        # ----------------------------------------------------
        # VALIDATE RESPONSE STRUCTURE
        # ----------------------------------------------------

        structure_check = validate_response_structure(
            parsed_response
        )

        # ----------------------------------------------------
        # GRADE MODEL RESPONSE
        # ----------------------------------------------------

        grade_result = grade_response(
            task,
            parsed_response
        )

        # ----------------------------------------------------
        # PREPARE EVALUATION RESULTS
        # ----------------------------------------------------

        output_data = {

            "task_id": task_id,

            "task_file": Path(task_file).name,

            "model": model_id,

            "status": "completed",

            "temperature": TEMPERATURE,

            "elapsed_seconds": round(elapsed, 2),

            "created_at_utc": utc_now(),

            "finish_reason": choice.finish_reason,

            "usage": usage,

            "structure_validation": structure_check,

            "raw_response": parsed_response,

            "grade_result": grade_result,

        }

        # ----------------------------------------------------
        # SAVE RESULTS
        # ----------------------------------------------------

        save_json(
            output_file,
            output_data
        )

        # ----------------------------------------------------
        # DISPLAY EVALUATION RESULTS
        # ----------------------------------------------------

        print(
            f"    [RESULT] {task_id} | {model_id}: "
            f"{grade_result['score']}/{grade_result['max_score']} "
            f"({grade_result['percentage']}%)"
        )

        if not structure_check["valid"]:

            print("    [WARNING] Response structure validation failed.")

            for item in structure_check["missing_fields"]:
                print(f"       Missing field: {item}")

            for item in structure_check["type_errors"]:
                print(f"       Type error: {item}")

        for rule in grade_result.get("rule_results", []):

            print(
                f"       {rule['rule_id']}: {rule['status']} "
                f"({rule['score']}/{rule['max_score']})"
            )

        print(f"    Saved: {output_file}")

        return {
            "task_id": task_id,
            "model": model_id,
            "status": "completed",
            "score": grade_result["score"],
            "max_score": grade_result["max_score"],
            "percentage": grade_result["percentage"],
            "critical_failure": grade_result["critical_failure"],
            "elapsed_seconds": round(elapsed, 2),
            "usage": usage,
            "result_file": str(output_file),
        }

    # --------------------------------------------------------
    # API AND EXECUTION ERRORS
    # --------------------------------------------------------

    except Exception as error:

        elapsed = time.time() - start_time

        output_data = {

            "task_id": task_id,

            "task_file": Path(task_file).name,

            "model": model_id,

            "status": "api_error",

            "error_type": type(error).__name__,

            "error": str(error),

            "elapsed_seconds": round(elapsed, 2),

            "created_at_utc": utc_now(),

        }

        save_json(
            output_file,
            output_data
        )

        print(f"    [ERROR] {type(error).__name__}: {error}")

        error_text = str(error).lower()

        if "402" in error_text or "requires more credits" in error_text:

            print(
                f"    [ACTION] OpenRouter could not fund the request. "
                f"MAX_TOKENS is {MAX_TOKENS}; reduce it or add credits."
            )

        elif (
            "no provider serves" in error_text
            or "no longer available" in error_text
        ):

            print(
                "    [ACTION] Check the model ID and provider availability."
            )

        return {
            "task_id": task_id,
            "model": model_id,
            "status": "error",
            "error_type": type(error).__name__,
            "error": str(error),
            "elapsed_seconds": round(elapsed, 2),
            "result_file": str(output_file),
        }


# ============================================================
# 8. BATCH SUMMARY
# ============================================================

def print_and_save_summary(results, task_count, model_count):

    completed = [
        item for item in results
        if item["status"] == "completed"
    ]

    failed = [
        item for item in results
        if item["status"] != "completed"
    ]

    print("\n========================================")

    print("FINAL BATCH SUMMARY")

    print("========================================")

    for item in results:

        if item["status"] == "completed":

            critical = (
                " | CRITICAL FAILURE"
                if item["critical_failure"]
                else ""
            )

            print(
                f"{item['task_id']} | {item['model']}: "
                f"{item['score']}/{item['max_score']} "
                f"({item['percentage']}%){critical}"
            )

        else:

            print(
                f"{item['task_id']} | {item['model']}: "
                f"ERROR - {item.get('error', 'Unknown error')}"
            )

    print("----------------------------------------")

    print(f"Tasks discovered: {task_count}")

    print(f"Models selected: {model_count}")

    print(f"Total attempts: {len(results)}")

    print(f"Successful evaluations: {len(completed)}")

    print(f"Failed evaluations: {len(failed)}")

    if completed:

        average_percentage = sum(
            item["percentage"] for item in completed
        ) / len(completed)

        print(
            f"Average percentage (completed runs): "
            f"{average_percentage:.2f}%"
        )

    else:

        average_percentage = None

        print("Average percentage: N/A")

    print("========================================")

    summary_data = {

        "status": "completed",

        "created_at_utc": utc_now(),

        "tasks_discovered": task_count,

        "models_selected": model_count,

        "total_attempts": len(results),

        "successful_evaluations": len(completed),

        "failed_evaluations": len(failed),

        "average_percentage_completed_runs": (
            round(average_percentage, 2)
            if average_percentage is not None
            else None
        ),

        "results": results,

    }

    save_json(SUMMARY_PATH, summary_data)

    print(f"Batch summary saved to: {SUMMARY_PATH}")


# ============================================================
# 9. MAIN BATCH EXECUTION
# ============================================================

def main():

    if not TASKS_DIR.exists():

        raise FileNotFoundError(
            f"Tasks directory not found: {TASKS_DIR}"
        )

    # Discover all task files automatically.
    task_files = sorted(TASKS_DIR.glob("task_*.json"))

    if not task_files:

        print(f"No task_*.json files found in: {TASKS_DIR}")

        return

    models_to_test = get_model_list()

    if not models_to_test:

        print("No models configured. Check OPENROUTER_MODELS in .env.")

        return

    print("\n========================================")

    print("PQC MIGRATION EVALUATION - BATCH RUN")

    print("========================================")

    print(f"Tasks found: {len(task_files)}")

    print(f"Models to test: {len(models_to_test)}")

    print(
        f"Total planned evaluations: "
        f"{len(task_files) * len(models_to_test)}"
    )

    print(f"Temperature: {TEMPERATURE}")

    print(f"Maximum output tokens: {MAX_TOKENS}")

    print("----------------------------------------")

    summary = []

    for task_index, task_file in enumerate(task_files):

        print(f"\n>>> LOADING TASK: {task_file.name}")

        try:

            task = load_json(task_file)

        except Exception as error:

            print(
                f"[TASK ERROR] Could not load "
                f"{task_file.name}: {error}"
            )

            for model_id in models_to_test:

                summary.append({
                    "task_id": task_file.stem,
                    "model": model_id,
                    "status": "error",
                    "error": f"Task loading failed: {error}",
                })

            continue

        if not isinstance(task, dict):

            print(
                f"[TASK ERROR] {task_file.name} "
                "must contain a JSON object."
            )

            for model_id in models_to_test:

                summary.append({
                    "task_id": task_file.stem,
                    "model": model_id,
                    "status": "error",
                    "error": "Task JSON top-level value must be an object.",
                })

            continue

        task_id = task.get("task_id", task_file.stem)

        for model_index, model_id in enumerate(models_to_test):

            result = run_model(
                model_id,
                task,
                task_file
            )

            summary.append(result)

            has_more_runs = (
                model_index < len(models_to_test) - 1
                or task_index < len(task_files) - 1
            )

            if has_more_runs and DELAY_BETWEEN_MODELS > 0:

                time.sleep(DELAY_BETWEEN_MODELS)

    print_and_save_summary(
        summary,
        task_count=len(task_files),
        model_count=len(models_to_test),
    )


# ============================================================
# 10. PROGRAM ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()