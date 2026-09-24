import os
import re
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from openai import OpenAI


# ============================================================
# CONFIG
# ============================================================

BASE_URL = "https://api.groq.com/openai/v1"

OUTPUT_DIR = Path("groq_results")

TEMPERATURE = 0.7


# ============================================================
# NEWSROOM QUESTIONS
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
# GROQ CLIENT
# ============================================================

def create_client():
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY was not found in your .env file."
        )

    return OpenAI(
        api_key=api_key,
        base_url=BASE_URL,
    )


# ============================================================
# GET MODELS
# ============================================================

def get_models():

    api_key = os.getenv("GROQ_API_KEY")

    response = requests.get(
        f"{BASE_URL}/models",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    models = []

    for model in data.get("data", []):

        if model.get("active", True):
            models.append(model["id"])

    return sorted(models)


# ============================================================
# SAFE FILE NAME
# ============================================================

def safe_filename(model_name):

    return re.sub(
        r'[<>:"/\\|?*]',
        "_",
        model_name,
    )


# ============================================================
# TEST MODEL
# ============================================================

def test_model(client, model_name):

    OUTPUT_DIR.mkdir(exist_ok=True)

    output_file = (
        OUTPUT_DIR /
        f"{safe_filename(model_name)}.txt"
    )

    print("\n" + "=" * 70)
    print(f"Testing: {model_name}")
    print("=" * 70)

    successful = 0
    failed = 0

    with open(
        output_file,
        "w",
        encoding="utf-8",
    ) as file:

        file.write("=" * 80 + "\n")
        file.write("NEWSROOM GROQ MODEL EVALUATION\n")
        file.write("=" * 80 + "\n\n")

        file.write(f"Model: {model_name}\n")
        file.write(
            "Started: "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )

        file.write(
            f"Questions: {len(QUESTIONS)}\n\n"
        )

        for index, item in enumerate(
            QUESTIONS,
            start=1,
        ):

            name = item["name"]
            question = item["question"].strip()

            print(
                f"[{index}/{len(QUESTIONS)}] "
                f"{name}..."
            )

            file.write("#" * 80 + "\n")
            file.write(
                f"TEST {index}: {name}\n"
            )
            file.write("#" * 80 + "\n\n")

            file.write("QUESTION:\n")
            file.write(question)
            file.write("\n\n")

            start = time.perf_counter()

            try:

                response = client.chat.completions.create(

                    model=model_name,

                    messages=[
                        {
                            "role": "system",
                            "content": """
You are an AI content engine being evaluated for
a technology news automation project called Newsroom.

Prioritize:

- factual accuracy
- clear reasoning
- concise writing
- following instructions
- avoiding invented information
- distinguishing facts from claims
- neutral news reporting
""",
                        },
                        {
                            "role": "user",
                            "content": question,
                        },
                    ],

                    temperature=TEMPERATURE,
                )

                elapsed = (
                    time.perf_counter() - start
                )

                answer = (
                    response.choices[0]
                    .message
                    .content
                )

                successful += 1

                file.write("RESPONSE:\n")
                file.write(answer)
                file.write("\n\n")

                file.write(
                    f"RESPONSE TIME: "
                    f"{elapsed:.2f} seconds\n"
                )

                print(
                    f"    ✓ Success "
                    f"({elapsed:.2f}s)"
                )

            except Exception as e:

                elapsed = (
                    time.perf_counter() - start
                )

                failed += 1

                file.write("ERROR:\n")
                file.write(str(e))
                file.write("\n\n")

                file.write(
                    f"RESPONSE TIME: "
                    f"{elapsed:.2f} seconds\n"
                )

                print(
                    f"    ✗ Failed "
                    f"({elapsed:.2f}s)"
                )

            file.write("\n")

        # ----------------------------------------------------
        # SUMMARY
        # ----------------------------------------------------

        file.write("=" * 80 + "\n")
        file.write("SUMMARY\n")
        file.write("=" * 80 + "\n\n")

        file.write(f"Model: {model_name}\n")
        file.write(f"Successful: {successful}\n")
        file.write(f"Failed: {failed}\n")
        file.write(
            f"Total: {len(QUESTIONS)}\n"
        )

    return successful, failed


# ============================================================
# MAIN
# ============================================================

def main():

    load_dotenv()

    client = create_client()

    print("=" * 70)
    print("NEWSROOM — GROQ MODEL BENCHMARK")
    print("=" * 70)

    print("\nRetrieving available Groq models...")

    models = get_models()

    print(
        f"\nFound {len(models)} active models."
    )

    print("\nModels:")

    for model in models:
        print(f"  - {model}")

    print("\n" + "-" * 70)

    total_success = 0
    total_failed = 0

    for model in models:

        success, failed = test_model(
            client,
            model,
        )

        total_success += success
        total_failed += failed

    print("\n" + "=" * 70)
    print("BENCHMARK COMPLETED")
    print("=" * 70)

    print(
        f"\nTotal requests: "
        f"{total_success + total_failed}"
    )

    print(
        f"Successful: {total_success}"
    )

    print(
        f"Failed: {total_failed}"
    )

    print(
        f"\nResults saved to:\n"
        f"  {OUTPUT_DIR.absolute()}"
    )


if __name__ == "__main__":
    main()