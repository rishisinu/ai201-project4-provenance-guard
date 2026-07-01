"""Provenance Guard: Flask backend.

Flow (see planning.md ## Architecture):
  POST /submit  -> llm_signal + stylometric_signal -> combine_scores -> audit log -> response
  POST /appeal  -> mark submission under_review -> audit log -> response
  GET  /review  -> reviewer UI, reads GET /queue (submissions under review)
  POST /review/<content_id>/decision -> reviewer overrides attribution -> audit log
  GET  /log     -> structured audit log, for grading/demo visibility
"""

import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import storage
from scoring import LABELS, combine_scores
from signals import llm_signal, stylometric_signal

load_dotenv()

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

VALID_ATTRIBUTIONS = set(LABELS.keys())


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/review")
def review_page():
    return render_template("review.html")


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    creator_id = (body.get("creator_id") or "anonymous").strip()

    if not text:
        return jsonify({"error": "text is required"}), 400

    llm_result = llm_signal(text)
    style_result = stylometric_signal(text)
    scored = combine_scores(llm_result["score"], style_result["score"])

    content_id = storage.new_content_id()
    timestamp = storage.now_iso()

    submission = {
        "content_id": content_id,
        "creator_id": creator_id,
        "text": text,
        "timestamp": timestamp,
        "llm_score": round(llm_result["score"], 4),
        "llm_reasoning": llm_result.get("reasoning", ""),
        "style_score": round(style_result["score"], 4),
        "style_breakdown": {
            "sentence_variance_score": round(style_result["sentence_variance_score"], 4),
            "punctuation_score": round(style_result["punctuation_score"], 4),
        },
        "combined_score": scored["combined_score"],
        "confidence": scored["confidence"],
        "attribution": scored["attribution"],
        "label": scored["label"],
        "status": "classified",
        "appeal_reasoning": None,
        "reviewer_notes": None,
    }
    storage.save_submission(submission)

    storage.log_event({
        "event": "submission",
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": timestamp,
        "attribution": scored["attribution"],
        "confidence": scored["confidence"],
        "combined_score": scored["combined_score"],
        "llm_score": submission["llm_score"],
        "style_score": submission["style_score"],
        "status": "classified",
    })

    return jsonify({
        "content_id": content_id,
        "attribution": scored["attribution"],
        "confidence": scored["confidence"],
        "combined_score": scored["combined_score"],
        "label": scored["label"],
        "signals": {
            "llm_score": submission["llm_score"],
            "llm_reasoning": submission["llm_reasoning"],
            "style_score": submission["style_score"],
            "style_breakdown": submission["style_breakdown"],
        },
        "status": submission["status"],
    })


@app.route("/appeal", methods=["POST"])
def appeal():
    body = request.get_json(silent=True) or {}
    content_id = body.get("content_id")
    creator_reasoning = (body.get("creator_reasoning") or "").strip()

    if not content_id or not creator_reasoning:
        return jsonify({"error": "content_id and creator_reasoning are required"}), 400

    submission = storage.get_submission(content_id)
    if submission is None:
        return jsonify({"error": "no submission found for that content_id"}), 404

    submission["status"] = "under_review"
    submission["appeal_reasoning"] = creator_reasoning

    storage.log_event({
        "event": "appeal",
        "content_id": content_id,
        "creator_id": submission["creator_id"],
        "original_attribution": submission["attribution"],
        "original_confidence": submission["confidence"],
        "appeal_reasoning": creator_reasoning,
        "status": "under_review",
    })

    return jsonify({
        "content_id": content_id,
        "status": "under_review",
        "message": "Appeal received. Your submission is queued for human review.",
    })


@app.route("/queue")
def queue():
    return jsonify({"entries": storage.submissions_under_review()})


@app.route("/review/<content_id>/decision", methods=["POST"])
def review_decision(content_id):
    body = request.get_json(silent=True) or {}
    reviewer_attribution = body.get("reviewer_attribution")
    reviewer_notes = (body.get("reviewer_notes") or "").strip()

    if reviewer_attribution not in VALID_ATTRIBUTIONS:
        return jsonify({"error": f"reviewer_attribution must be one of {sorted(VALID_ATTRIBUTIONS)}"}), 400

    submission = storage.get_submission(content_id)
    if submission is None:
        return jsonify({"error": "no submission found for that content_id"}), 404

    previous_attribution = submission["attribution"]
    submission["attribution"] = reviewer_attribution
    submission["label"] = LABELS[reviewer_attribution]
    submission["status"] = "resolved"
    submission["reviewer_notes"] = reviewer_notes

    storage.log_event({
        "event": "review_decision",
        "content_id": content_id,
        "creator_id": submission["creator_id"],
        "previous_attribution": previous_attribution,
        "reviewer_attribution": reviewer_attribution,
        "reviewer_notes": reviewer_notes,
        "status": "resolved",
    })

    return jsonify({"content_id": content_id, "submission": submission})


@app.route("/status/<content_id>")
def status(content_id):
    submission = storage.get_submission(content_id)
    if submission is None:
        return jsonify({"error": "no submission found for that content_id"}), 404

    return jsonify({
        "content_id": content_id,
        "status": submission["status"],
        "attribution": submission["attribution"],
        "confidence": submission["confidence"],
        "label": submission["label"],
        "reviewer_notes": submission["reviewer_notes"],
    })


@app.route("/log")
def log():
    return jsonify({"entries": storage.get_log()})


if __name__ == "__main__":
    app.run(debug=True)
