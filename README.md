# ai201-project4-provenance-guard

## Rate Limiting Setting Table

| Window     | Limit | Rationale                                                           |
| ---------- | ----- | ------------------------------------------------------------------- |
| per minute | 10    | Allows quick draft → revise → resubmit iteration; blocks rapid bursts |
| per hour   | 60    | A long, active editing session — well above normal human pace       |
| per day    | 100   | Generous daily ceiling that still caps sustained abuse              |

## Capture Rate Limiting Log Entries

```text
200  ← requests 1–10 accepted (within the 10/minute limit)
200
200
200
200
200
200
200
200
200
429  ← request 11 blocked: Too Many Requests
429  ← request 12 blocked
```

## 3 Audit Log Entries

```json
[
  {
    "content_id": "ef031a14-5c41-4226-8e90-b0c2d3b23d2a",
    "creator_id": "demo-1",
    "timestamp": "2026-06-30T03:44:27.615043+00:00",
    "attribution": "likely_ai",
    "combined_confidence": 0.77,
    "status": "under_review",
    "llm_score": 0.85,
    "sh_score": 0.66,
    "event_type": "appeal",
    "appeal_classification": null,
    "appeal_reason": "I wrote this myself for a work report; it just reads formally."
  },
  {
    "content_id": "dad57e17-51e4-4378-ae09-bcc72efb58ec",
    "creator_id": "demo-2",
    "timestamp": "2026-06-30T03:44:27.610947+00:00",
    "attribution": "likely_human",
    "combined_confidence": 0.17,
    "status": "classified",
    "llm_score": 0.2,
    "sh_score": 0.13,
    "event_type": "submission",
    "appeal_classification": null,
    "appeal_reason": null
  },
  {
    "content_id": "ef031a14-5c41-4226-8e90-b0c2d3b23d2a",
    "creator_id": "demo-1",
    "timestamp": "2026-06-30T03:44:27.307276+00:00",
    "attribution": "likely_ai",
    "combined_confidence": 0.77,
    "status": "classified",
    "llm_score": 0.85,
    "sh_score": 0.66,
    "event_type": "submission",
    "appeal_classification": null,
    "appeal_reason": null
  }
]
```


## Architecture overview
the path a submission takes from input to transparency label


## Detection signals
what each signal measures, why you chose it, and what it misses


## Confidence scoring
why this scoring approach, what you'd change if you were deploying this for real.
How I combined signals into a score, how you validated it's meaningful, and two example submissions with noticeably different confidence scores (one high-confidence, one lower-confidence) showing the actual scores



## Transparency label
typed description of all three variants (high-confidence AI, human, uncertain) showing the exact text each one displays; screenshot or mockup optional
Include a typed description of all three variants (high-confidence AI, high-confidence human, uncertain) — write out the exact text each one displays. You're welcome to include a screenshot or mockup as well, but the written description is what's required.


## Rate limiting
the limits you chose and your reasoning for those specific values. Name at least one specific type of content your system would likely get wrong and explain why — tied to a property of your signals, not a generic "it needs more data."

## Known limitations
at least one specific type of content your system would likely misclassify and why


## Spec reflection
one way the spec helped you, one way implementation diverged from it and why


## AI usage section
At least 2 specific instances describing what you directed the AI to do and what you revised or overrode
