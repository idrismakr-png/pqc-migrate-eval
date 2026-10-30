
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

TASK_PATH = BASE_DIR / "tasks" / "task_001.json"
RESULTS_DIR = BASE_DIR / "results"

RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Models to evaluate.
DEFAULT_MODELS = [
    "anthropic/claude-sonnet-4.6",
    "openai/gpt-4o",
]

TEMPERATURE = 0.0

# Reduced to fit your current OpenRouter token allowance.
MAX_TOKENS = 3000

REQUEST_TIMEOUT = 180

DELAY_BETWEEN_MODELS = 2


# ============================================================
# 2. ENVIRONMENT AND API CONFIGURATION
# ============================================================

load_dotenv(BASE_DIR / ".env")

API_KEY = os.getenv("OPENROUTER_API_KEY")

if not API_KEY:
    raise ValueError(
        "OPENROUTER_API_KEY not found in .env. "
        "Please add your OpenRouter API key."
    )

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
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

    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False
        )


def safe_filename(model_id):

    filename = str(model_id).replace("/", "_")

    filename = re.sub(
        r"[^A-Za-z0-9_.-]+",
        "_",
        filename
    )

    return filename.strip("._") or "unknown_model"


def get_output_path(model_id):

    filename = safe_filename(model_id)

    return RESULTS_DIR / f"{filename}_task001.json"


# ============================================================
# 4. MODEL CONFIGURATION
# ============================================================

def get_model_list():

    """
    Models can be changed without editing this file.

    Add this to .env if you want to override the defaults:

    OPENROUTER_MODELS=provider/model1,provider/model2
    """

    configured_models = os.getenv(
        "OPENROUTER_MODELS",
        ""
    ).strip()

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
        "confidence"
    ]

    expected_types = {
        "migration_steps": list,
        "blockers": list,
        "vendor_dependencies": list,
        "algorithm_roles": dict,
        "budget": dict,
        "confidence": str
    }

    missing_fields = []

    type_errors = []

    for field in required_fields:

        if field not in response:
            missing_fields.append(field)

    for field, expected_type in expected_types.items():

        if field in response:

            if not isinstance(
                response[field],
                expected_type
            ):

                type_errors.append(
                    f"{field} should be "
                    f"{expected_type.__name__}, "
                    f"not {type(response[field]).__name__}."
                )

    return {
        "valid": (
            len(missing_fields) == 0
            and len(type_errors) == 0
        ),
        "missing_fields": missing_fields,
        "type_errors": type_errors
    }


# ============================================================
# 6. TOKEN USAGE EXTRACTION
# ============================================================

def extract_usage(response):

    usage = getattr(response, "usage", None)

    if usage is None:
        return None

    if hasattr(usage, "model_dump"):
        return usage.model_dump()

    if isinstance(usage, dict):
        return usage

    return str(usage)


# ============================================================
# 7. PROMPT CONSTRUCTION
# ============================================================

def build_prompt(task):

    schema = task.get(
        "expected_output_schema",
        {}
    )

    prompt = f"""
You are an expert enterprise cybersecurity architect
specialising in post-quantum cryptography migration
for financial institutions.

Your task is to develop a technically defensible,
practical first-phase PQC migration plan.

SCENARIO:

{task["scenario"]}


QUESTION:

{task["question"]}


EXPECTED OUTPUT STRUCTURE:

{json.dumps(schema, indent=2, ensure_ascii=False)}


IMPORTANT INSTRUCTIONS:

1. Return exactly one valid JSON object.

2. Do not include Markdown code fences or explanatory
   text outside the JSON object.

3. Use the exact top-level field names specified
   in the expected output structure.

4. Use arrays for migration_steps, blockers,
   vendor_dependencies, and cost_assumptions.

5. Use integer values for step_number.

6. Use YYYY-MM-DD dates, or null where a date
   cannot responsibly be determined.

7. Use only the activity_type values specified
   in the expected output structure.

8. ML-KEM must be used for key establishment.
   It must not be assigned to digital signatures.

9. ML-DSA must be used for digital signatures.
   It must not be assigned to key establishment.

10. Do not claim that Thales Luna Network HSM 7
    supports ML-KEM or ML-DSA.

11. Do not claim that the third-party core banking
    platform supports PQC.

12. Both vendor dependencies remain unconfirmed
    unless written evidence is explicitly provided
    in the scenario.

13. Do not schedule production cryptographic changes,
    HSM firmware upgrades, or major application
    deployments from 1 December 2026 through
    15 January 2027 inclusive.

14. Prioritise sensitive information that must remain
    confidential for 10 to 15 years.

15. Explain harvest-now-decrypt-later exposure.

16. Provide a numeric estimated_total_usd.

17. Provide a numeric cost breakdown that reconciles
    with the total estimate.

18. Keep the first-phase budget at or below
    USD 250,000.

19. Distinguish planning and non-production activities
    from production deployment.

20. Do not invent vendor confirmations, firmware
    versions, delivery dates, product capabilities,
    or regulatory approvals.

Return only the JSON object.
"""

    return prompt.strip()


# ============================================================
# 8. RUN MODEL EVALUATION
# ============================================================

def run_model(
    model_id,
    task,
    temperature=TEMPERATURE
):

    print(f"\nRunning model: {model_id}...")

    start_time = time.time()

    output_file = get_output_path(model_id)

    prompt = build_prompt(task)

    try:

        # ----------------------------------------------------
        # Send request to OpenRouter
        # ----------------------------------------------------

        response = client.chat.completions.create(

            model=model_id,

            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a careful enterprise "
                        "cybersecurity architect. Follow "
                        "all instructions and return "
                        "valid JSON only."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],

            temperature=temperature,

            max_tokens=MAX_TOKENS,

            response_format={
                "type": "json_object"
            }
        )

        elapsed = time.time() - start_time

        choice = response.choices[0]

        content = choice.message.content

        # ----------------------------------------------------
        # Check for empty response
        # ----------------------------------------------------

        if not content or not content.strip():

            error_data = {
                "model": model_id,
                "status": "empty_response",
                "elapsed_seconds": round(elapsed, 2),
                "created_at_utc": datetime.now(
                    timezone.utc
                ).isoformat(),
                "usage": extract_usage(response)
            }

            save_json(output_file, error_data)

            print("ERROR: Model returned an empty response.")

            return None

        # ----------------------------------------------------
        # Parse JSON response
        # ----------------------------------------------------

        try:

            parsed_response = json.loads(content)

        except json.JSONDecodeError as error:

            error_data = {
                "model": model_id,
                "status": "invalid_json",
                "error": str(error),
                "raw_text": content,
                "elapsed_seconds": round(elapsed, 2),
                "created_at_utc": datetime.now(
                    timezone.utc
                ).isoformat(),
                "finish_reason": choice.finish_reason,
                "usage": extract_usage(response)
            }

            save_json(output_file, error_data)

            print("ERROR: Model did not return valid JSON.")

            print(f"Details: {error}")

            print(f"Raw output saved to: {output_file}")

            return None

        if not isinstance(parsed_response, dict):

            error_data = {
                "model": model_id,
                "status": "invalid_json_structure",
                "error": "Top-level JSON must be an object.",
                "raw_response": parsed_response
            }

            save_json(output_file, error_data)

            print("ERROR: JSON response is not an object.")

            return None

        print(
            f"Response received in {elapsed:.2f} seconds."
        )

        # ----------------------------------------------------
        # Validate response structure
        # ----------------------------------------------------

        structure_check = validate_response_structure(
            parsed_response
        )

        # ----------------------------------------------------
        # Grade model response
        # ----------------------------------------------------

        grade_result = grade_response(
            task,
            parsed_response
        )

        # ----------------------------------------------------
        # Prepare evaluation results
        # ----------------------------------------------------

        output_data = {

            "model": model_id,

            "status": "completed",

            "temperature": temperature,

            "elapsed_seconds": round(elapsed, 2),

            "created_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),

            "finish_reason": choice.finish_reason,

            "usage": extract_usage(response),

            "structure_validation": structure_check,

            "raw_response": parsed_response,

            "grade_result": grade_result

        }

        # ----------------------------------------------------
        # Save results
        # ----------------------------------------------------

        save_json(
            output_file,
            output_data
        )

        # ----------------------------------------------------
        # Display evaluation results
        # ----------------------------------------------------

        print("\n----------------------------------------")

        print(f"MODEL: {model_id}")

        print(
            f"SCORE: {grade_result['score']} / "
            f"{grade_result['max_score']}"
        )

        print(
            f"PERCENTAGE: {grade_result['percentage']}%"
        )

        print(
            "STRUCTURE VALIDATION: "
            + (
                "PASS"
                if structure_check["valid"]
                else "WARNING"
            )
        )

        if grade_result["critical_failure"]:

            print("CRITICAL FAILURE DETECTED")

        print("\nRULE-BY-RULE RESULTS")

        for item in grade_result["rule_results"]:

            print(
                f"{item['rule_id']}: "
                f"{item['status']} "
                f"({item['score']} / {item['max_score']})"
            )

        if grade_result["failures"]:

            print("\nFAILURES")

            for failure in grade_result["failures"]:

                print(f"[FAIL] {failure}")

        print("----------------------------------------")

        print(f"Results saved to: {output_file}")

        return grade_result

    # --------------------------------------------------------
    # API and execution errors
    # --------------------------------------------------------

    except Exception as error:

        elapsed = time.time() - start_time

        error_data = {

            "model": model_id,

            "status": "api_error",

            "error_type": type(error).__name__,

            "error": str(error),

            "elapsed_seconds": round(elapsed, 2),

            "created_at_utc": datetime.now(
                timezone.utc
            ).isoformat()

        }

        save_json(
            output_file,
            error_data
        )

        print(f"\nAPI ERROR: {error}")

        error_text = str(error).lower()

        if (
            "no longer available" in error_text
            or "no provider serves" in error_text
        ):

            print(
                "ACTION: This model is unavailable. "
                "Select another model from "
                "https://openrouter.ai/models"
            )

        elif (
            "requires more credits" in error_text
            or "402" in error_text
        ):

            print(
                f"ACTION: OpenRouter cannot fund this request. "
                f"The current MAX_TOKENS value is {MAX_TOKENS}. "
                "Reduce it or add credits/increase the key limit."
            )

        print(f"Error saved to: {output_file}")

        return None


# ============================================================
# 9. EVALUATION SUMMARY
# ============================================================

def print_summary(results):

    print("\n========================================")

    print("MODEL EVALUATION SUMMARY")

    print("========================================")

    successful = 0

    failed = 0

    for model_id, result in results:

        if result is None:

            failed += 1

            print(f"{model_id}: ERROR")

        else:

            successful += 1

            print(
                f"{model_id}: "
                f"{result['score']}/"
                f"{result['max_score']} "
                f"({result['percentage']}%)"
            )

    print("----------------------------------------")

    print(f"Successful evaluations: {successful}")

    print(f"Failed evaluations: {failed}")

    print(f"Total models attempted: {len(results)}")

    print("========================================")


# ============================================================
# 10. MAIN EXECUTION
# ============================================================

def main():

    if not TASK_PATH.exists():

        raise FileNotFoundError(
            f"Task file not found: {TASK_PATH}"
        )

    task = load_json(TASK_PATH)

    models_to_test = get_model_list()

    print("\n========================================")

    print("PQC MIGRATION MODEL EVALUATION")

    print("========================================")

    print(
        f"Task ID: {task.get('task_id', 'Unknown')}"
    )

    print(
        f"Models to test: {len(models_to_test)}"
    )

    print(
        f"Temperature: {TEMPERATURE}"
    )

    print(
        f"Maximum output tokens: {MAX_TOKENS}"
    )

    print("----------------------------------------")

    results = []

    for index, model_id in enumerate(models_to_test):

        result = run_model(
            model_id,
            task
        )

        results.append(
            (model_id, result)
        )

        if index < len(models_to_test) - 1:

            time.sleep(
                DELAY_BETWEEN_MODELS
            )

    print_summary(results)


if __name__ == "__main__":

    main()

