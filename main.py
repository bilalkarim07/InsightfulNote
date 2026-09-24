import os
import csv
import requests
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


# ============================================================
# CONFIGURATION
# ============================================================

OLLAMA_BASE_URL = "https://ollama.com/v1"
OLLAMA_MODELS_URL = f"{OLLAMA_BASE_URL}/models"

OUTPUT_FILE = "ollama_model_test_results.csv"

load_dotenv()


# ============================================================
# TEST QUESTIONS
# ============================================================

TEST_QUESTIONS = [
    {
        "category": "Reasoning",
        "question": (
            "A farmer has 17 sheep. All but 9 die. "
            "How many sheep are left? Explain your reasoning briefly."
        ),
    },
    {
        "category": "Coding",
        "question": (
            "Write a Python function that takes a list of integers "
            "and returns the second largest unique number. "
            "Handle the case where fewer than two unique numbers exist."
        ),
    },
    {
        "category": "Structured Output",
        "question": (
            "Return a JSON object with exactly these keys: "
            "title, summary, category, and keywords. "
            "Create the object for a fictional news story about "
            "a new AI model being released."
        ),
    },
    {
        "category": "Creative Writing",
        "question": (
            "Write a short motivational social media post about "
            "consistency. Keep it under 50 words."
        ),
    },
    {
        "category": "News Content",
        "question": (
            "Write a concise social media post explaining why "
            "AI agents are becoming important for software development. "
            "Make it informative, engaging, and suitable for a news "
            "and technology account."
        ),
    },
]


# ============================================================
# GET API KEY
# ============================================================

def get_api_key():
    api_key = os.getenv("OLLAMA_API_KEY")

    if not api_key:
        raise RuntimeError(
            "OLLAMA_API_KEY was not found in your environment."
        )

    return api_key


# ============================================================
# GET MODELS
# ============================================================

def get_available_models(api_key):
    headers = {
        "Authorization": f"Bearer {api_key}"
    }

    response = requests.get(
        OLLAMA_MODELS_URL,
        headers=headers,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    models = data.get("data", [])

    return [
        model.get("id")
        for model in models
        if model.get("id")
    ]


# ============================================================
# TEST SINGLE MODEL
# ============================================================

def test_model(model, question):
    """
    Test one model with one question.

    Returns:
        status, response, error
    """

    try:

        llm = ChatOpenAI(
            model=model,
            base_url=OLLAMA_BASE_URL,
            api_key=os.environ["OLLAMA_API_KEY"],
            use_responses_api=False,
            temperature=0.7,
        )

        result = llm.invoke(question)

        return (
            "success",
            result.content,
            "",
        )

    except Exception as error:

        return (
            "error",
            "",
            str(error),
        )


# ============================================================
# SAVE RESULT
# ============================================================

def save_result(
    writer,
    model,
    category,
    question,
    status,
    response,
    error,
):

    writer.writerow(
        {
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "category": category,
            "question": question,
            "status": status,
            "response": response,
            "error": error,
        }
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 80)
    print("OLLAMA CLOUD MODEL BENCHMARK")
    print("=" * 80)

    # --------------------------------------------------------
    # API KEY
    # --------------------------------------------------------

    api_key = get_api_key()

    print("✓ OLLAMA_API_KEY found.")

    # --------------------------------------------------------
    # GET MODELS
    # --------------------------------------------------------

    print("\nRetrieving models from Ollama Cloud...")

    models = get_available_models(api_key)

    print(
        f"✓ Found {len(models)} models."
    )

    for index, model in enumerate(models, 1):
        print(f"  {index:>2}. {model}")

    # --------------------------------------------------------
    # CSV
    # --------------------------------------------------------

    output_path = Path(OUTPUT_FILE)

    fieldnames = [
        "timestamp",
        "model",
        "category",
        "question",
        "status",
        "response",
        "error",
    ]

    successful_models = set()
    failed_models = set()

    with open(
        output_path,
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as csv_file:

        writer = csv.DictWriter(
            csv_file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        # ----------------------------------------------------
        # TEST EVERY MODEL
        # ----------------------------------------------------

        total_tests = len(models) * len(TEST_QUESTIONS)

        current_test = 0

        for model_index, model in enumerate(models, 1):

            print("\n" + "=" * 80)
            print(
                f"MODEL {model_index}/{len(models)}: {model}"
            )
            print("=" * 80)

            model_success = False

            for question_index, test in enumerate(
                TEST_QUESTIONS,
                1,
            ):

                current_test += 1

                print(
                    f"\n[{current_test}/{total_tests}] "
                    f"{test['category']}"
                )

                print(
                    "Question:",
                    test["question"],
                )

                status, response, error = test_model(
                    model=model,
                    question=test["question"],
                )

                # --------------------------------------------
                # SUCCESS
                # --------------------------------------------

                if status == "success":

                    model_success = True
                    successful_models.add(model)

                    print("\n✓ SUCCESS")
                    print("\nResponse:")
                    print(response)

                # --------------------------------------------
                # ERROR
                # --------------------------------------------

                else:

                    failed_models.add(model)

                    print("\n✗ FAILED")
                    print(error)

                # --------------------------------------------
                # SAVE
                # --------------------------------------------

                save_result(
                    writer=writer,
                    model=model,
                    category=test["category"],
                    question=test["question"],
                    status=status,
                    response=response,
                    error=error,
                )

                # Flush after every test so the CSV
                # survives interruptions.

                csv_file.flush()

            if model_success:
                print(
                    f"\n✓ {model} completed at least one test."
                )
            else:
                print(
                    f"\n✗ {model} failed all tests."
                )

    # ========================================================
    # SUMMARY
    # ========================================================

    print("\n\n" + "=" * 80)
    print("BENCHMARK COMPLETE")
    print("=" * 80)

    print(
        f"\nTotal models tested: {len(models)}"
    )

    print(
        f"Models with successful requests: "
        f"{len(successful_models)}"
    )

    print(
        f"Models with failures: "
        f"{len(failed_models)}"
    )

    print("\nSuccessful models:")

    for model in successful_models:
        print(f"  ✓ {model}")

    print("\nFailed models:")

    for model in failed_models:
        print(f"  ✗ {model}")

    print(
        f"\nResults saved to:\n"
        f"{output_path.absolute()}"
    )


if __name__ == "__main__":
    main()