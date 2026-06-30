import os
import re
import json
import uuid

from flask import Flask, request, jsonify, render_template
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from groq import Groq

from audit_log import log_event, read_log, init_db, get_submission

load_dotenv()

app = Flask(__name__)

# Ensure the audit-log table exists before any request writes to it.
init_db()

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

# ---------------------------------------------------------------------------
# Groq client (used by the LLM-based classification signal)
# ---------------------------------------------------------------------------
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
LLM_MODEL = "llama-3.3-70b-versatile"


# ---------------------------------------------------------------------------
# Detection Signal 1 — LLM-based classification (Groq)  [diagram node B]
#
# Measures whether the text reads as human- or AI-generated based on its
# overall semantic, structural, and stylistic patterns.
#
# Output: an AI-likelihood score between 0.00 and 1.00, where higher means
# more likely AI-generated. A per-signal attribution label is derived from
# the same confidence thresholds used for the combined score.
# ---------------------------------------------------------------------------
def _score_to_attribution(ai_score):
    """Map an AI-likelihood score (0.00–1.00) to a transparency attribution."""
    if ai_score >= 0.75:
        return "likely_ai"
    if ai_score >= 0.40:
        return "uncertain"
    return "likely_human"


def llm_classify(text_id, raw_text):
    """LLM-based classification signal.

    Sends the raw text to Groq and asks for a structured AI-likelihood
    judgement. Returns the diagram's node-B contract plus a short rationale
    (useful for the appeals queue):
        {text_id, llm_attribution, llm_confidence_score, llm_reasoning}

    If the API call or response parsing fails, falls back to a neutral
    "uncertain" result rather than raising into the request handler.
    """
    system_prompt = (
        "You are a text-provenance classifier. Assess whether the text reads "
        "as human-written or AI-generated based on its overall semantic, "
        "structural, and stylistic patterns. Respond with ONLY a JSON object "
        "of the form "
        '{"ai_score": <float 0.00-1.00>, "reasoning": "<one sentence>"}, '
        "where 0.00 means almost certainly human-written and 1.00 means almost "
        "certainly AI-generated. Do not include any text outside the JSON object."
    )

    try:
        completion = groq_client.chat.completions.create(
            model=LLM_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": raw_text},
            ],
        )
        parsed = json.loads(completion.choices[0].message.content)
        ai_score = float(parsed.get("ai_score", 0.5))
        reasoning = parsed.get("reasoning", "")
    except (json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
        # Malformed / unexpected model output — degrade gracefully.
        ai_score, reasoning = 0.5, f"parse_error: {exc}"
    except Exception as exc:  # network / API errors
        ai_score, reasoning = 0.5, f"api_error: {exc}"

    # Clamp to the documented 0.00–1.00 range in case the model drifts.
    ai_score = max(0.0, min(1.0, ai_score))

    return {
        "text_id": text_id,
        "llm_attribution": _score_to_attribution(ai_score),
        "llm_confidence_score": round(ai_score, 2),
        "llm_reasoning": reasoning,
    }


# ---------------------------------------------------------------------------
# Detection Signal 2 — Stylometric heuristics  [diagram node C]
#
# Measures statistical properties of the writing and maps each to an
# AI-likelihood proxy in [0, 1], then blends them into one stylometric score:
#   1) Lexical sophistication (average word length) — casual human writing
#      uses short, common words; AI/formal prose uses longer abstract words.
#      This is the strongest stylometric discriminator in testing.
#   2) Average sentence length (complexity) — longer sentences read more AI-like.
#   3) Sentence-length variance (burstiness) — humans vary sentence length a
#      lot; uniform lengths read more AI-like.
#   4) Punctuation density — clause-heavy formal punctuation (commas, colons,
#      semicolons) per sentence reads more AI-like.
#
# Type-token ratio (vocabulary diversity) is also computed and reported, but
# it is excluded from the blend: for short submissions it saturates near 1.0
# for human and AI text alike, so it does not discriminate.
#
# Output: {text_id, sh_attribution, sh_confidence_score}
# ---------------------------------------------------------------------------
def _clamp01(x):
    return max(0.0, min(1.0, x))


def stylometric_classify(text_id, raw_text):
    text = (raw_text or "").strip()
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    words = re.findall(r"[A-Za-z']+", text)
    sentence_word_counts = [len(re.findall(r"[A-Za-z']+", s)) for s in sentences]
    sentence_word_counts = [c for c in sentence_word_counts if c > 0]

    # Edge case (per spec): too little text to analyze reliably -> stay neutral.
    if len(sentence_word_counts) < 2 or len(words) < 10:
        return {
            "text_id": text_id,
            "sh_attribution": "uncertain",
            "sh_confidence_score": 0.5,
            "sh_reasoning": "insufficient_text: too short for reliable stylometry",
        }

    n_sentences = len(sentence_word_counts)

    # Metric 1 — lexical sophistication (average word length).
    #            Short common words read human; long abstract words read AI.
    avg_word_len = sum(len(w) for w in words) / len(words)
    ai_word = _clamp01((avg_word_len - 4.0) / (6.0 - 4.0))  # 4.0 chars -> 0, 6.0+ -> 1

    # Metric 2 — average sentence length (complexity).
    #            Longer sentences read more AI-like.
    mean_len = sum(sentence_word_counts) / n_sentences
    ai_length = _clamp01((mean_len - 8.0) / (22.0 - 8.0))  # 8 words -> 0, 22+ -> 1

    # Metric 3 — sentence-length variance via coefficient of variation.
    #            Low variation (uniform sentences) reads more AI-like.
    variance = sum((c - mean_len) ** 2 for c in sentence_word_counts) / n_sentences
    cv = (variance ** 0.5) / mean_len if mean_len else 0.0
    ai_variance = _clamp01(1 - min(cv, 0.75) / 0.75)  # cv 0 -> 1.0, cv>=0.75 -> 0.0

    # Metric 4 — punctuation density (clause-marking punctuation per sentence).
    #            Heavy clause punctuation reads more AI-like.
    clause_marks = len(re.findall(r"[,;:]", text))
    punct_per_sentence = clause_marks / n_sentences
    ai_punctuation = _clamp01(punct_per_sentence / 1.5)  # 0/sent -> 0, >=1.5/sent -> 1

    # Type-token ratio is reported for transparency but not blended (see header).
    ttr = len({w.lower() for w in words}) / len(words)

    # Weighted blend (lexical sophistication is the strongest discriminator).
    sh_score = (
        0.40 * ai_word
        + 0.20 * ai_length
        + 0.20 * ai_variance
        + 0.20 * ai_punctuation
    )
    sh_score = round(_clamp01(sh_score), 2)

    return {
        "text_id": text_id,
        "sh_attribution": _score_to_attribution(sh_score),
        "sh_confidence_score": sh_score,
        "sh_reasoning": (
            f"avg_word_len={avg_word_len:.2f}, avg_sentence_len={mean_len:.1f}, "
            f"sentence_len_cv={cv:.2f}, punct_per_sentence={punct_per_sentence:.2f}, "
            f"ttr={ttr:.2f} (unblended)"
        ),
    }


# ---------------------------------------------------------------------------
# Confidence scoring  [diagram node D]
#
# Combines the two signals via the weighted average defined in planning.md:
#     combined = (0.6 * llm_ai_score) + (0.4 * stylometric_ai_score)
# The combined score is mapped to a transparency attribution using the
# confidence thresholds (0.75-1.00 likely_ai, 0.40-0.74 uncertain,
# 0.00-0.39 likely_human).
# ---------------------------------------------------------------------------
LLM_WEIGHT = 0.6
SH_WEIGHT = 0.4


def score_confidence(llm_result, sh_result):
    llm_score = llm_result["llm_confidence_score"]
    sh_score = sh_result["sh_confidence_score"]
    combined = round(LLM_WEIGHT * llm_score + SH_WEIGHT * sh_score, 2)

    return {
        "attribution": _score_to_attribution(combined),
        "llm_attribution": llm_result["llm_attribution"],
        "llm_confidence_score": llm_score,
        "sh_attribution": sh_result["sh_attribution"],
        "sh_confidence_score": sh_score,
        "combined_avg_confidence_score": combined,
    }


# ---------------------------------------------------------------------------
# Transparency label generation  [diagram node E]
#
# Maps the combined confidence score to a transparency label. The variant is
# chosen via the same thresholds used for attribution; the label text is the
# verbatim copy from planning.md's "Transparency label design" section.
# ---------------------------------------------------------------------------
TRANSPARENCY_LABELS = {
    "likely_ai": {
        "label_variant": "Likely AI-Generated",
        "label_text": (
            "The system found **strong evidence** that the content was generated "
            "or substantially assisted by AI and has **high confidence**. If you "
            "believe the result is incorrect, you may submit an appeal for review."
        ),
    },
    "uncertain": {
        "label_variant": "Uncertain",
        "label_text": (
            "The system found **mixed evidence**, and we couldn't confidently "
            "determine whether the content is AI-generated or human-written. If "
            "you are the creator and believe this result requires review, you may "
            "submit an appeal."
        ),
    },
    "likely_human": {
        "label_variant": "Likely Human-Generated",
        "label_text": (
            "The system found **strong evidence** that the content was created by "
            "a human author and has **high confidence**. If you believe the result "
            "is incorrect, you may submit an appeal for review."
        ),
    },
}


def generate_label(combined_score):
    """Map a combined confidence score to its transparency label details."""
    attribution = _score_to_attribution(combined_score)
    variant = TRANSPARENCY_LABELS[attribution]
    return {
        "attribution": attribution,
        "label_variant": variant["label_variant"],
        "label_text": variant["label_text"],
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/log", methods=["GET"])
def get_log():
    return jsonify({"entries": read_log()})


# Rate limits sized for one creator submitting their own work, not a script:
#   - 10/minute  : allows quick draft-then-revise iteration, blocks rapid floods
#   - 60/hour    : a long, active editing session, well above normal human pace
#   - 100/day    : a generous daily ceiling that still caps sustained abuse
SUBMIT_RATE_LIMITS = "10 per minute;60 per hour;100 per day"


@app.route("/submit", methods=["POST"])
@limiter.limit(SUBMIT_RATE_LIMITS)
def submit():
    data = request.get_json(silent=True) or {}

    raw_text = data.get("text")
    creator_id = data.get("creator_id")

    # Required fields must be present before we do any work.
    if not raw_text or not creator_id:
        return jsonify({"error": "Both 'text' and 'creator_id' are required."}), 400

    content_id = str(uuid.uuid4())

    # Signal 1 — LLM-based classification (Groq) [diagram node B].
    llm_result = llm_classify(content_id, raw_text)
    # Signal 2 — stylometric heuristics [diagram node C].
    sh_result = stylometric_classify(content_id, raw_text)
    # Confidence scoring — weighted average of both signals [diagram node D].
    scored = score_confidence(llm_result, sh_result)
    # Transparency label generation [diagram node E].
    label = generate_label(scored["combined_avg_confidence_score"])

    response = {
        "content_id": content_id,
        "attribution": scored["attribution"],
        "confidence": scored["combined_avg_confidence_score"],
        "llm_confidence_score": scored["llm_confidence_score"],
        "sh_confidence_score": scored["sh_confidence_score"],
        "label_variant": label["label_variant"],
        "label_text": label["label_text"],
        "status": "classified",
    }

    log_event({
        "content_id": content_id,
        "creator_id": creator_id,
        "event_type": "submission",
        "attribution": scored["attribution"],
        "combined_confidence": scored["combined_avg_confidence_score"],
        "llm_score": scored["llm_confidence_score"],
        "sh_score": scored["sh_confidence_score"],
        "status": "classified",
    })

    return jsonify(response)


@app.route("/appeal", methods=["POST"])
def appeal():
    data = request.get_json(silent=True) or {}

    content_id = data.get("content_id")
    creator_reasoning = data.get("creator_reasoning")
    # Optional: the classification the creator believes is correct.
    appeal_classification = data.get("appeal_classification")

    # An appeal must identify the content and explain the disagreement.
    if not content_id or not creator_reasoning:
        return jsonify({
            "error": "content_id and creator_reasoning are required."
        }), 400

    # Link the appeal to the original attribution decision.
    original = get_submission(content_id)
    if original is None:
        return jsonify({"error": f"No submission found for content_id {content_id}."}), 404

    # Status update: classified -> under_review. Logged as a new audit entry
    # that carries the original classification decision alongside the appeal,
    # so the content's current status (latest event) is "under_review".
    log_event({
        "content_id": content_id,
        "creator_id": original.get("creator_id"),
        "event_type": "appeal",
        "attribution": original.get("attribution"),
        "combined_confidence": original.get("combined_confidence"),
        "llm_score": original.get("llm_score"),
        "sh_score": original.get("sh_score"),
        "appeal_classification": appeal_classification,
        "appeal_reason": creator_reasoning,
        "status": "under_review",
    })

    # Confirmation carries the original decision + appeal details for the
    # human reviewer's appeal queue [diagram node M].
    label = generate_label(original.get("combined_confidence") or 0.0)
    response = {
        "content_id": content_id,
        "status": "under_review",
        "original_attribution": original.get("attribution"),
        "llm_attribution": _score_to_attribution(original.get("llm_score") or 0.0),
        "llm_confidence_score": original.get("llm_score"),
        "sh_attribution": _score_to_attribution(original.get("sh_score") or 0.0),
        "sh_confidence_score": original.get("sh_score"),
        "combined_avg_confidence_score": original.get("combined_confidence"),
        "label_details": label,
        "appeal_classification": appeal_classification,
        "creator_reasoning": creator_reasoning,
        "message": "Your appeal was received and is under review.",
    }

    return jsonify(response)


if __name__ == "__main__":
    app.run(port=5000, debug=True)
