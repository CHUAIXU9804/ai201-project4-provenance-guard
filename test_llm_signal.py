"""Standalone harness for the LLM-based classification signal (Groq).

Calls llm_classify() directly with a few representative inputs and prints
the structured output, so the signal can be inspected before it is wired
into the /submit endpoint.

Run:  python test_llm_signal.py
"""
from app import llm_classify

SAMPLES = [
    (
        "text 1",
        "Furthermore, it is important to note that leveraging synergistic "
        "methodologies can significantly enhance operational efficiency across "
        "multiple domains, thereby facilitating optimal outcomes in a holistic "
        "and scalable manner.",
    ),
    (
        "text 2",
        "ngl i totally forgot to buy milk again lol. my fridge is basically "
        "just condiments at this point. gonna grab some tmrw maybe idk.",
    ),
    (
        "text 3",
        "Great product, works fine.",
    ),
    (
        "text 4",
        "The Industrial Revolution reshaped not only the means of production "
        "but also the social fabric of nineteenth-century Britain, displacing "
        "rural labor and concentrating populations in rapidli growing cities.",
    ),
    
    (
        "test 89",
        "1, 2, 3, 4, 5, 6, 7, 8, 9, 10",
        
    )
]


def main():
    for label, text in SAMPLES:
        result = llm_classify(label, text)
        print(f"\n=== {label} ===")
        print(f"  input:        {text[:70]}...")
        print(f"  attribution:  {result['llm_attribution']}")
        print(f"  score:        {result['llm_confidence_score']}")
        print(f"  reasoning:    {result['llm_reasoning']}")


if __name__ == "__main__":
    main()
