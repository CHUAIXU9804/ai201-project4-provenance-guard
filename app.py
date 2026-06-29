import os
import json
import uuid

from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from groq import Groq

from audit_log import log_event, read_log

load_dotenv()

app = Flask(__name__)

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
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def home():
    return "Provenance Guard is running."


@app.route("/log", methods=["GET"])
def get_log():
    # return jsonify({"entries": read_log()})
    return jsonify({"entries": []})


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    data = request.get_json(silent=True) or {}

    raw_text = data.get("text")
    creator_id = data.get("creator_id")

    # Required fields must be present before we do any work.
    if not raw_text or not creator_id:
        return jsonify({"error": "Both 'text' and 'creator_id' are required."}), 400

    text_id = str(uuid.uuid4())

    # Hardcoded stub response — verify the route wiring before adding logic.
    # TODO: Signal 1 — LLM-based classification (Groq) [diagram node B]
    # TODO: Signal 2 — stylometric heuristics [node C]
    # TODO: confidence scoring / weighted average [node D]
    # TODO: transparency label generation [node E]
    response = {
        "content_id": text_id,
        "attribution": "uncertain",
        "confidence": 0.5,
        "label": "We're not sure who wrote this.",
        "status": "classified",
    }

    return jsonify(response)


@app.route("/appeal", methods=["POST"])
def appeal():
    data = request.get_json()

    content_id = data.get("content_id")
    reasoning = data.get("creator_reasoning")

    response = {
        "content_id": content_id,
        "status": "under_review",
        "message": "Your appeal was received and is under review.",
    }

    log_event({
        "content_id": content_id,
        "creator_reasoning": reasoning,
        "status": "under_review",
        "event_type": "appeal",
    })

    return jsonify(response)


if __name__ == "__main__":
    app.run(port=5000, debug=True)
