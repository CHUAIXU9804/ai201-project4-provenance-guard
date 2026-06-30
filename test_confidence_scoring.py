"""Verification for the confidence scoring logic [diagram node D].

Checks the two acceptance criteria for the combined score:
  (1) It varies meaningfully across clearly different inputs — a polished,
      uniform paragraph vs. a casual, irregular one should score differently.
  (2) It maps to at least 3 distinct label categories.

Part A runs both signals end-to-end on multi-sentence inputs (hits Groq).
Part B feeds synthetic signal pairs straight into score_confidence() to prove
the mapping deterministically reaches all three categories (no network).

Run:  python test_confidence_scoring.py
"""
from app import llm_classify, stylometric_classify, score_confidence, _score_to_attribution

# Multi-sentence inputs so BOTH signals actually run (no stylometry abstain).
INPUTS = [
    (
        "clearly-AI",
        "Artificial intelligence represents a transformative paradigm shift in "
        "modern society. It is important to note that while the benefits of AI "
        "are numerous, it is equally essential to consider the ethical "
        "implications. Furthermore, stakeholders across various sectors must "
        "collaborate to ensure responsible deployment.",
    ),
    (
        "clearly-human",
        "ok so i finally tried that new ramen place downtown and honestly? "
        "underwhelming. the broth was fine but they put WAY too much sodium in "
        "it and i was thirsty for like three hours after. my friend got the "
        "spicy version and said it was better. probably won't go back unless "
        "someone drags me there",
    ),
    (
        "formal-human",
        "The relationship between monetary policy and asset price inflation has "
        "been extensively studied in the literature. Central banks face a "
        "fundamental tension between their mandate for price stability and the "
        "unintended consequences of prolonged low interest rates on equity and "
        "real estate valuations.",
    ),
    (
        "edited-AI",
        "I've been thinking a lot about remote work lately. There are genuine "
        "tradeoffs — flexibility and no commute on one side, isolation and "
        "blurred work-life boundaries on the other. Studies show productivity "
        "varies widely by individual and role type.",
    ),
]


def part_a_end_to_end():
    print("=== Part A: end-to-end (both signals + combined) ===")
    print(f"{'input':<18} {'llm':>5} {'styl':>5} {'combined':>9}  label")
    print("-" * 60)
    combined_scores = []
    for label, text in INPUTS:
        llm = llm_classify(label, text)
        styl = stylometric_classify(label, text)
        scored = score_confidence(llm, styl)
        combined_scores.append(scored["combined_avg_confidence_score"])
        print(f"{label:<18} {llm['llm_confidence_score']:>5.2f} "
              f"{styl['sh_confidence_score']:>5.2f} "
              f"{scored['combined_avg_confidence_score']:>9.2f}  "
              f"{scored['attribution']}")
    spread = max(combined_scores) - min(combined_scores)
    print(f"\n  score spread (max-min) = {spread:.2f}  "
          f"-> {'MEANINGFUL variation' if spread >= 0.2 else 'LOW variation'}")


def part_b_mapping():
    print("\n=== Part B: label mapping is deterministic & 3 categories reachable ===")
    # Synthetic (llm, sh) pairs chosen to land in each band.
    cases = [
        (0.95, 0.90),  # -> high   -> likely_ai
        (0.55, 0.50),  # -> middle -> uncertain
        (0.10, 0.15),  # -> low    -> likely_human
    ]
    labels_seen = set()
    for llm_s, sh_s in cases:
        scored = score_confidence(
            {"llm_confidence_score": llm_s, "llm_attribution": _score_to_attribution(llm_s)},
            {"sh_confidence_score": sh_s, "sh_attribution": _score_to_attribution(sh_s)},
        )
        labels_seen.add(scored["attribution"])
        print(f"  llm={llm_s:.2f} sh={sh_s:.2f} -> "
              f"combined={scored['combined_avg_confidence_score']:.2f} "
              f"-> {scored['attribution']}")
    print(f"\n  distinct labels reached: {sorted(labels_seen)}")
    assert labels_seen == {"likely_ai", "uncertain", "likely_human"}, labels_seen
    print("  PASS: all three categories reachable.")


if __name__ == "__main__":
    part_a_end_to_end()
    part_b_mapping()
