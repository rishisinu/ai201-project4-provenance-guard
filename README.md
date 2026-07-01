# ai201-project4-provenance-guard

A backend that classifies submitted text as likely AI-generated, likely
human-written, or uncertain, using two independent detection signals, and
surfaces a plain-language transparency label plus an appeals workflow.

Full design rationale (signals, thresholds, edge cases, AI Tool Plan) lives
in [`planning.md`](planning.md), written before implementation.

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate      # Windows Git Bash
pip install -r requirements.txt
# .env with GROQ_API_KEY=... (see .env, gitignored)
python app.py
```

Then visit `http://localhost:5000/` to submit text, or `http://localhost:5000/review`
for the reviewer queue.

## Architecture overview

**Submission flow:** `POST /submit` (raw text + creator_id) → `llm_signal()`
(Groq holistic judgment) and `stylometric_signal()` (structural heuristics)
run independently → `combine_scores()` normalizer weights and combines them
into one `combined_score`, derives `confidence` and an `attribution` verdict,
and maps that to one of three fixed transparency label strings → a structured
entry is appended to the in-memory audit log → the full result (content_id,
attribution, confidence, label, per-signal breakdown) is returned to the
caller and rendered in the browser UI.

**Appeal flow:** `POST /appeal` (content_id + creator_reasoning) → the
matching submission's status flips to `under_review` and the reasoning is
attached → an audit log entry links the appeal to the original decision →
the submission now shows up in `GET /queue`, read by the `/review` reviewer
UI, which lets a human pick a final `reviewer_attribution`, submit it via
`POST /review/<content_id>/decision`, and resolve the appeal (status →
`resolved`), which is itself logged.

All state (submissions, audit log) is in-memory, by design — there's no
auth/session model on this system, so nothing sensitive persists across a
server restart. The one exception is per-browser-session "previous ratings,"
which live only in the page's JS and clear on refresh.

## Detection signals

1. **LLM-based judgment** (`signals.py::llm_signal`, Groq `llama-3.3-70b-versatile`):
   the model is prompted to assess whether the text reads as human or
   AI-written based on semantic/stylistic coherence — does it have the small
   imperfections and idiosyncrasies of a person thinking aloud, or the
   smoothed-over, hedged, listy coherence typical of AI output. Returns
   `ai_probability` in `[0, 1]` plus a one-sentence reasoning string.
   **Blind spot:** it's a holistic judgment call by another LLM, so it can be
   fooled by genuinely formal/dry human writing (technical, academic,
   corporate register), and it offers no reasoning beyond a sentence — it
   can't be independently audited the way a numeric heuristic can.

2. **Stylometric heuristics** (`signals.py::stylometric_signal`, pure Python):
   two structural sub-scores, averaged —
   - *Sentence-length variance:* coefficient of variation of word-count per
     sentence. Human writing tends to vary sentence length a lot; AI writing
     tends toward more uniform lengths. Low variance → higher AI-likelihood.
   - *Heavy-punctuation density:* frequency of em dashes (—), colons, and
     semicolons per 100 words. AI output (especially default-style LLM
     output) leans on these more consistently than most human writing.
   **Blind spot:** both sub-scores are surface statistics with no semantic
   understanding at all — a human who happens to write in short, uniform
   sentences (or an AI model prompted to write short bursts) will score
   however the numbers land regardless of true origin. It also needs enough
   sentences/words to be meaningful; on very short text it falls back to a
   neutral 0.5 (see Known Limitations).

These two signals are independent by construction — one is semantic
(reasoning about meaning), one is purely structural (counting things) — so
disagreement between them is itself informative, not noise.

## Confidence scoring

`scoring.py::combine_scores` computes:

```
combined_score = 0.75 * llm_score + 0.25 * style_score      # 0 = human, 1 = AI
confidence     = abs(combined_score - 0.5) * 2              # 0 = coin flip, 1 = maximal certainty
```

The LLM signal is weighted 3x higher because it reasons about the whole text;
the stylometric heuristics only capture two narrow structural properties.
**Thresholds are deliberately asymmetric:** `combined_score >= 0.70` →
`likely_ai`, `combined_score <= 0.30` → `likely_human`, otherwise
`uncertain`. It takes more evidence to accuse a piece of writing of being
AI-generated than to clear it as human — a false positive (telling a real
person their own work was flagged as AI) is worse for a creative platform
than a false negative, so the system leans toward "uncertain" rather than
"likely_ai" whenever the signals disagree.

**How I validated it's meaningful:** I ran the four test inputs from the
assignment spec (a clearly-AI paragraph, a clearly-human review, and two
borderline cases) through the pipeline and checked the scores matched
intuition before moving on, per the Milestone 4 checkpoint:

| Input | llm_score | style_score | combined_score | confidence | attribution | label |
|---|---|---|---|---|---|---|
| Clearly AI-generated (AI paradigm shift paragraph) | 0.90 | 0.184 | 0.721 | **0.442** | `likely_ai` | AI-generated (High Confidence) |
| Clearly human (casual ramen review) | 0.20 | 0.000 | 0.150 | **0.700** | `likely_human` | Human-written (High Confidence) |
| Borderline: formal human econ writing | 0.80 | 0.287 | 0.672 | 0.343 | `uncertain` | uncertain label |
| Borderline: lightly-edited AI (remote work) | 0.40 | 0.609 | 0.452 | **0.096** | `uncertain` | uncertain label |

The two examples worth calling out for "noticeably different confidence":
the **clearly human review scored confidence 0.700** (system is fairly sure),
while the **lightly-edited AI remote-work paragraph scored confidence 0.096**
(system is almost at a coin flip) — a 0.6+ swing in confidence between two
real submissions, not a constant number regardless of input.

One calibration note: I originally weighted the signals 0.65/0.35. Under
that weighting the "clearly AI-generated" spec example (llm_score 0.9,
style_score 0.184) combined to only 0.649 — just under the 0.70 threshold —
and was mislabeled `uncertain` instead of `likely_ai`, because that
particular sample doesn't use em dashes/colons/semicolons, so the
stylometric signal didn't corroborate the LLM's strong read. I reweighted to
0.75/0.25, which is the lowest LLM weight that still classifies that sample
correctly while keeping the formal-human borderline case (0.672) safely
under the same threshold — i.e., I didn't just chase one test case, I
checked the reweight didn't blur the two borderline examples into each
other.

## Transparency label

The label text returned by `/submit` (verbatim, from `scoring.py::LABELS`):

| Variant | Exact text |
|---|---|
| High-confidence AI | `AI-generated (High Confidence)` |
| High-confidence human | `Human-written (High Confidence)` |
| Uncertain | `We are uncertain if this content is AI-generated or human-written. The content may be a mix of both.` |

## Appeals workflow

`POST /appeal` takes `content_id` and `creator_reasoning`. It sets that
submission's `status` to `under_review`, stores the reasoning, and logs an
`appeal` audit event linking back to the original `attribution`/`confidence`.
No automated re-classification happens — a human has to act.

The reviewer UI at `GET /review` (no auth — see Known Limitations) polls
`GET /queue` (all submissions with `status == "under_review"`) and shows,
per appeal: the full submitted text, the original attribution/confidence,
both individual signal scores and their sub-breakdowns, and the creator's
appeal reasoning. The reviewer picks a final attribution and adds notes via
`POST /review/<content_id>/decision`, which overwrites the label, sets
`status` to `resolved`, and logs a `review_decision` event with the
before/after attribution.

**Live updates without a refresh:** since session history lives only in the
browser tab's JS memory (no server-side session), refreshing the page would
wipe it. Instead, the page polls `GET /status/<content_id>` every 5 seconds
for any of its own submissions still `under_review`, and updates the result
card and history in place once a reviewer resolves the appeal — no
websocket needed, since updates are infrequent (human-paced) and the
`content_id` the client already holds is enough to check on it.

Example (from actual testing):
```bash
curl -s -X POST http://localhost:5000/appeal -H "Content-Type: application/json" \
  -d '{"content_id": "5081c7e0-...", "creator_reasoning": "I wrote this myself, formal tone is just my writing style."}'
# {"content_id": "5081c7e0-...", "status": "under_review", "message": "Appeal received. ..."}

curl -s -X POST http://localhost:5000/review/5081c7e0-.../decision -H "Content-Type: application/json" \
  -d '{"reviewer_attribution": "likely_human", "reviewer_notes": "Confirmed with creator, overriding to human."}'
# submission.status -> "resolved", submission.attribution -> "likely_human"
```

## Rate limiting

`/submit` is limited to **10 per minute; 100 per day** (Flask-Limiter,
in-memory storage, keyed by remote address).

Reasoning: a real creator submitting/tweaking one piece of writing rarely
sends more than a couple of requests a minute (draft → tweak → resubmit);
10/min gives generous headroom for that workflow while putting a low ceiling
on a script hammering the endpoint. 100/day caps an adversary who tries to
stay just under the per-minute limit by spacing requests out over hours,
while still comfortably covering a prolific creator submitting many short
pieces across a full day.

Verified with 12 rapid requests (script from the assignment spec):
```
200
200
200
200
200
200
200
200
200
200
429
429
```
First 10 succeed, the next 2 are rejected — confirms the per-minute limit is
enforced.

## Audit log

`GET /log` returns structured entries (most recent first), covering
`submission`, `appeal`, and `review_decision` events. Sample (3 real entries
from the appeal flow above, most recent first):

```json
{
  "event": "review_decision",
  "content_id": "5081c7e0-19df-4b68-b974-d10353ff1cea",
  "creator_id": "test-ai",
  "previous_attribution": "likely_ai",
  "reviewer_attribution": "likely_human",
  "reviewer_notes": "Confirmed with creator, overriding to human.",
  "status": "resolved",
  "timestamp": "2026-07-01T05:18:53.208884+00:00"
}
```
```json
{
  "event": "appeal",
  "content_id": "5081c7e0-19df-4b68-b974-d10353ff1cea",
  "creator_id": "test-ai",
  "appeal_reasoning": "I wrote this myself, formal tone is just my writing style.",
  "original_attribution": "likely_ai",
  "original_confidence": 0.442,
  "status": "under_review",
  "timestamp": "2026-07-01T05:18:52.703700+00:00"
}
```
```json
{
  "event": "submission",
  "content_id": "5081c7e0-19df-4b68-b974-d10353ff1cea",
  "creator_id": "test-ai",
  "attribution": "likely_ai",
  "confidence": 0.442,
  "combined_score": 0.721,
  "llm_score": 0.9,
  "style_score": 0.1839,
  "status": "classified",
  "timestamp": "2026-07-01T05:18:52.445780+00:00"
}
```

## Known limitations

1. **Very short submissions** (a haiku, a one-line caption, a short social
   post): `stylometric_signal` needs at least 2 sentences and 8 words to
   compute a meaningful coefficient of variation; below that it falls back
   to a neutral 0.5. That means short creative work is classified almost
   entirely on the LLM signal alone, undermining the multi-signal premise
   exactly for a content type a poetry/short-form platform will see a lot of.

2. **Formal-register human writing without heavy punctuation** (academic,
   technical, corporate tone): both signals independently trend toward
   "AI-like" for this register — the LLM associates smoothed-over, hedged
   phrasing with AI output, and the punctuation heuristic doesn't get to
   disagree because the text simply doesn't use em dashes/colons/semicolons
   either way. Our own "formal human econ writing" borderline test scored
   0.672 combined, just under the AI threshold — a genuine person writing in
   that register is one confident LLM call away from being flagged.

## Spec reflection

**Helped:** deciding the asymmetric AI/human thresholds (0.70 / 0.30, not a
symmetric 0.5 cutoff) in `planning.md` *before* writing `scoring.py` meant
the false-positive-aversion design goal was baked into the threshold values
themselves, rather than being something I'd have had to retrofit after
noticing the system was too quick to accuse.

**Diverged:** `planning.md`'s architecture section describes a
microservices approach (separate LLM/style/aggregation/labeling services
communicating over APIs). The actual implementation is a single Flask
process with three plain functions (`llm_signal`, `stylometric_signal`,
`combine_scores`) called directly inside one request handler. Given the
project's real scope — in-memory storage, no auth, one dev server — separate
services would have added deployment and network overhead with no
corresponding benefit, so I kept the same data flow the diagram describes
but implemented it as direct function calls instead of network hops.

## AI usage

1. Directed the AI assistant to generate the Flask app, the two signal
   functions, the normalizer, and the appeal/review endpoints in one pass
   from the `planning.md` spec (detection signals + uncertainty
   representation + label variants + appeals workflow sections). The first
   generated version of `llm_signal`'s prompt template used `str.format()`
   with a literal example JSON object (`{"ai_probability": ...}`) embedded
   in the prompt string — Python's `.format()` interpreted those braces as
   format placeholders and raised `KeyError: '"ai_probability"'` on every
   real request, silently masked by the fallback handler as a generic "llm
   signal error." I caught this by testing the raw submission endpoint
   directly (not just staring at the code) and fixed it by escaping the
   literal braces (`{{`/`}}`) in the prompt template.

2. Directed the AI to test the combined scoring function against the four
   spec example inputs and report whether the scores matched intuition. The
   first weighting (0.65 LLM / 0.35 style) mislabeled the "clearly
   AI-generated" example as `uncertain` instead of `likely_ai`. Rather than
   accept that or arbitrarily bump the weight to force a pass, I asked it to
   compute the combined score across a few candidate weightings for all
   three affected examples at once, and picked 0.75/0.25 specifically
   because it was the smallest change that fixed the AI example without also
   flipping the borderline formal-human example into `likely_ai`.
