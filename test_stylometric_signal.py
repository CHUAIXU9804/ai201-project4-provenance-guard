"""Standalone harness for the stylometric heuristics signal (Signal 2).

Runs BOTH signals on the same inputs used for Signal 1 (reuses SAMPLES from
test_llm_signal.py), combines them with the weighted-average formula from
planning.md:

    combined_score = (0.6 * llm_ai_score) + (0.4 * stylometric_ai_score)

and reports whether the two signals AGREE or DISAGREE on the attribution.

Run:  python test_stylometric_signal.py
"""
from app import llm_classify, stylometric_classify, score_confidence
from test_llm_signal import SAMPLES


def main():
    print(f"{'label':<10} {'llm':>5} {'styl':>5} {'comb':>5}  "
          f"{'llm_attr':<13} {'styl_attr':<13} {'agree?':<9} final")
    print("-" * 85)

    for label, text in SAMPLES:
        llm = llm_classify(label, text)
        styl = stylometric_classify(label, text)
        scored = score_confidence(llm, styl)

        agree = "AGREE" if llm["llm_attribution"] == styl["sh_attribution"] else "DISAGREE"

        print(f"{label:<10} "
              f"{llm['llm_confidence_score']:>5.2f} "
              f"{styl['sh_confidence_score']:>5.2f} "
              f"{scored['combined_avg_confidence_score']:>5.2f}  "
              f"{llm['llm_attribution']:<13} "
              f"{styl['sh_attribution']:<13} "
              f"{agree:<9} "
              f"{scored['attribution']}")
        print(f"           stylometry: {styl['sh_reasoning']}")


if __name__ == "__main__":
    main()
