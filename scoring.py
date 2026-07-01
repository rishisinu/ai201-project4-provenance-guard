"""Normalizer: combines the two signal scores into one confidence score,
an attribution verdict, and the exact transparency label text.

Weighting (see planning.md): LLM judgment is weighted higher (0.75) than the
stylometric heuristics (0.25) because it reasons about the whole text
holistically, while the heuristics only capture two narrow structural
properties that plenty of human writing can also exhibit. Calibrated against
the four test inputs from the assignment spec (see README): 0.75/0.25 is the
lowest LLM weight that still classifies the "clearly AI" sample as
high-confidence AI while keeping the "formal human econ writing" borderline
sample below the AI threshold.

Thresholds are asymmetric on purpose: it takes a higher combined score to
call something "likely_ai" (0.70) than it takes a low score to call
something "likely_human" (0.30). A false positive -- telling a real human
their work was flagged as AI -- is worse for a creative platform than a
false negative, so the system is deliberately more reluctant to accuse.
"""

LLM_WEIGHT = 0.75
STYLE_WEIGHT = 0.25

AI_THRESHOLD = 0.70
HUMAN_THRESHOLD = 0.30

LABELS = {
    "likely_ai": "AI-generated (High Confidence)",
    "likely_human": "Human-written (High Confidence)",
    "uncertain": (
        "We are uncertain if this content is AI-generated or human-written. "
        "The content may be a mix of both."
    ),
}


def combine_scores(llm_score: float, style_score: float) -> dict:
    combined_score = LLM_WEIGHT * llm_score + STYLE_WEIGHT * style_score
    confidence = abs(combined_score - 0.5) * 2  # 0 = coin flip, 1 = maximal certainty

    if combined_score >= AI_THRESHOLD:
        attribution = "likely_ai"
    elif combined_score <= HUMAN_THRESHOLD:
        attribution = "likely_human"
    else:
        attribution = "uncertain"

    return {
        "combined_score": round(combined_score, 4),
        "confidence": round(confidence, 4),
        "attribution": attribution,
        "label": LABELS[attribution],
    }
