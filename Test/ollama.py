import os
import re
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


# ============================================================
# CONFIGURATION
# ============================================================

OLLAMA_BASE_URL = "https://ollama.com/v1"

# Add/remove models here
MODELS = [
    "gpt-oss:120b",
    "gpt-oss:20b",
    "nemotron-3-super",
    "nemotron-3-ultra",
    "gemma4:31b",
    "nemotron-3-nano:30b",
]

TEMPERATURE = 0.7

OUTPUT_DIR = Path("results")


# ============================================================
# NEWSROOM TEST QUESTIONS
# ============================================================

QUESTIONS = [

    {
        "name": "News Understanding",
        "question": """
You are the AI content engine for my Newsroom project.

A technology company has announced a new AI model. The company claims
that the model is significantly better than its previous model at
coding, reasoning, and mathematics.

However, independent benchmark results have not yet been published,
and journalists are currently reporting only the company's claims.

Explain:

1. Which parts of this information are confirmed facts?
2. Which parts are claims?
3. What information should be verified before publishing?
4. How should Newsroom report this story without presenting
   unverified claims as established facts?
""",
    },

    {
        "name": "News Post Generation",
        "question": """
Using the following scenario, create a short Newsroom-style post
for X and Threads.

Scenario:

A technology company has announced a new AI model. The company says
the model is significantly better than its previous model at coding,
reasoning, and mathematics. Independent benchmark results have not
yet been published.

Write a concise, informative post under 80 words.

Do not invent benchmark numbers or present the company's claims
as independently verified facts.
""",
    },

    {
        "name": "Breaking News",
        "question": """
Newsroom receives the following breaking-news information:

"OpenAI has released a new AI model today. The company says the model
is faster and more capable than its previous generation and is now
available to developers."

Create a breaking-news style post suitable for X.

Rules:

- Keep it under 60 words.
- Do not invent technical specifications.
- Clearly attribute claims to the company.
- Do not use exaggerated language.
- Make it informative and engaging.
""",
    },

    {
        "name": "Fact vs Claim",
        "question": """
Newsroom is processing this information:

"Company X says its new AI model is the world's most powerful model,
beats every competitor on reasoning benchmarks, and will transform
software development."

Classify each statement as one of:

FACT
COMPANY CLAIM
REQUIRES VERIFICATION

Then explain briefly why you classified each statement that way.
Do not perform external research.
""",
    },

    {
        "name": "Headline Generation",
        "question": """
Generate 5 possible headlines for a Newsroom post about this story:

"A new open-source AI model has been released. Its developers report
strong performance on several coding and reasoning benchmarks."

Requirements:

- Headlines should be concise.
- Avoid clickbait.
- Do not invent benchmark scores.
- Clearly communicate that the model has been released.
- Make them suitable for a technology news account.
""",
    },

    {
        "name": "Social Media Rewrite",
        "question": """
Rewrite the following news information into a concise social media
post for Newsroom:

"Google announced a new AI model. According to Google, the model
improves performance across several tasks and is designed for
developers building AI applications."

Requirements:

- Under 70 words.
- Neutral news tone.
- Preserve the important information.
- Do not add facts that are not provided.
- Do not exaggerate Google's claims.
""",
    },

    {
        "name": "Incomplete Information",
        "question": """
Newsroom receives this incomplete report:

"Several users are reporting that a major AI service is currently
unavailable. The company's official account has not yet confirmed
an outage."

What should Newsroom do?

Explain:

1. Whether the story should immediately be presented as a confirmed
   outage.
2. What should be verified.
3. How the story could be reported while information is still developing.
4. Provide an example post under 60 words.
""",
    },

    {
        "name": "Conflicting Reports",
        "question": """
Newsroom receives two reports about an AI product launch.

Report A says the product launched today.

Report B, published by another technology publication, says the launch
has been delayed until next month.

Neither report provides an official announcement.

Explain how Newsroom should handle the conflicting information.

Then write a short post that communicates the situation without
pretending that either report has been confirmed.
""",
    },

    {
        "name": "AI Technology Explanation",
        "question": """
Write a short Newsroom post explaining why AI agents are becoming
important for software development.

Requirements:

- Under 80 words.
- Explain the concept simply.
- Mention that agents can perform multi-step tasks.
- Avoid hype.
- Make it understandable to someone who is not an AI engineer.
""",
    },

    {
        "name": "Newsroom Editorial Judgment",
        "question": """
Newsroom has this information:

"An AI startup claims its new model is 10x better than GPT-class
models, but provides no benchmark methodology, independent testing,
or detailed results."

Explain how Newsroom should approach this story.

Then write a responsible social media post about it.

The goal is to inform readers without amplifying an unsupported claim.
""",
    },
]


# ============================================================
# HELPERS
# ============================================================

def safe_filename(model_name: str) -> str:
    """
    Convert model name into a Windows-safe filename.
    """
    return re.sub(r'[<>:"/\\|?*]', "_", model_name)


def create_llm(model_name: str):
    """
    Create an Ollama Cloud ChatOpenAI client.
    """
    return ChatOpenAI(
        model=model_name,
        base_url=OLLAMA_BASE_URL,
        api_key=os.getenv("OLLAMA_API_KEY"),
        use_responses_api=False,
        temperature=TEMPERATURE,
    )


def write_header(file, model_name: str):
    file.write("=" * 80 + "\n")
    file.write("NEWSROOM MODEL EVALUATION\n")
    file.write("=" * 80 + "\n\n")

    file.write(f"Model: {model_name}\n")
    file.write(
        f"Test started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    )
    file.write(f"Questions: {len(QUESTIONS)}\n")
    file.write("\n")

    file.write("=" * 80 + "\n\n")


# ============================================================
# TEST ONE MODEL
# ============================================================

def test_model(model_name: str):

    print("\n" + "=" * 70)
    print(f"Testing: {model_name}")
    print("=" * 70)

    OUTPUT_DIR.mkdir(exist_ok=True)

    filename = safe_filename(model_name) + ".txt"
    output_file = OUTPUT_DIR / filename

    try:
        llm = create_llm(model_name)
    except Exception as e:
        print(f"Could not initialize model: {e}")
        return

    successful = 0
    failed = 0

    with open(output_file, "w", encoding="utf-8") as file:

        write_header(file, model_name)

        for index, item in enumerate(QUESTIONS, start=1):

            question_name = item["name"]
            question = item["question"].strip()

            print(
                f"[{index}/{len(QUESTIONS)}] "
                f"{question_name}..."
            )

            file.write("#" * 80 + "\n")
            file.write(f"TEST {index}: {question_name}\n")
            file.write("#" * 80 + "\n\n")

            file.write("QUESTION:\n")
            file.write(question)
            file.write("\n\n")

            start_time = time.perf_counter()

            try:

                response = llm.invoke(
                    [
                        (
                            "system",
                            """
You are an AI content engine being evaluated for a
technology news automation project called Newsroom.

Prioritize:
- factual accuracy
- clear reasoning
- concise writing
- following instructions
- avoiding invented information
- distinguishing facts from claims
- neutral news reporting
""",
                        ),
                        ("user", question),
                    ]
                )

                elapsed = time.perf_counter() - start_time

                answer = response.content

                successful += 1

                file.write("RESPONSE:\n")
                file.write(answer)
                file.write("\n\n")

                file.write(
                    f"RESPONSE TIME: {elapsed:.2f} seconds\n"
                )

                file.write("\n\n")

                print(
                    f"    ✓ Success "
                    f"({elapsed:.2f}s)"
                )

            except Exception as e:

                elapsed = time.perf_counter() - start_time

                failed += 1

                error_message = str(e)

                file.write("ERROR:\n")
                file.write(error_message)
                file.write("\n\n")

                file.write(
                    f"RESPONSE TIME: {elapsed:.2f} seconds\n"
                )

                file.write("\n\n")

                print(
                    f"    ✗ Failed "
                    f"({elapsed:.2f}s)"
                )

        # ====================================================
        # SUMMARY
        # ====================================================

        file.write("=" * 80 + "\n")
        file.write("TEST SUMMARY\n")
        file.write("=" * 80 + "\n\n")

        file.write(f"Model: {model_name}\n")
        file.write(f"Successful: {successful}\n")
        file.write(f"Failed: {failed}\n")
        file.write(f"Total: {len(QUESTIONS)}\n")

    print("\nCompleted:")
    print(f"  Model: {model_name}")
    print(f"  Successful: {successful}")
    print(f"  Failed: {failed}")
    print(f"  Output: {output_file}")


# ============================================================
# MAIN
# ============================================================

def main():

    load_dotenv()

    if not os.getenv("OLLAMA_API_KEY"):
        raise RuntimeError(
            "OLLAMA_API_KEY was not found.\n"
            "Add it to your .env file."
        )

    print("=" * 70)
    print("NEWSROOM OLLAMA MODEL EVALUATOR")
    print("=" * 70)

    print(f"\nModels: {len(MODELS)}")
    print(f"Questions per model: {len(QUESTIONS)}")
    print(f"Total requests: {len(MODELS) * len(QUESTIONS)}")

    print("\nOutput directory:")
    print(f"  {OUTPUT_DIR.absolute()}")

    for model in MODELS:
        test_model(model)

    print("\n" + "=" * 70)
    print("ALL TESTS COMPLETED")
    print("=" * 70)

    print(f"\nResults are available in:")
    print(f"  {OUTPUT_DIR.absolute()}")


if __name__ == "__main__":
    main()