"""Supported and unsupported questions used by the retrieval evaluation."""

# These cover coursework, dining, housing, transportation, and administrative
# policies. Each has a specific expected phrase so answer quality is scorable.
QUESTIONS = [
    # {"question": "...", "expects": "..."},
    {"question": "How are juniors and seniors ranked in the housing lottery?", "expects": "credit hours"},
    {"question": "Are the CS 340 midterm and final open-book?", "expects": "open-book"},
    {"question": "What time does Halden Hall close?", "expects": "7:00pm"},
    {"question": "When is the best time to do laundry in Aldridge Hall?", "expects": "Tuesday or Wednesday morning"},
    {"question": "How long does it take to walk from Fenwick Court to central campus?", "expects": "18 minutes"},
]

# Clearly unrelated questions used to evaluate the relevance gate. Refusals do
# not reach Gemini and therefore consume no generation tokens.
OUT_OF_SCOPE = [
    "What is the capital of Mongolia?",
    "How do I change the oil in a diesel engine?",
    "Who won the 1994 World Cup?",
    "What is the recommended dosage of ibuprofen for a headache?",
    "How do I write a for loop in Rust?",
]


def answered() -> list[dict]:
    """Return configured questions with nonempty text."""
    return [q for q in QUESTIONS if q.get("question", "").strip()]
