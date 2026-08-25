"""
Vercel serverless entry point.

Exposes the LangGraph agent as a small JSON API - no UI, just endpoints
your instructor (or a script/Postman/curl) can hit directly:

  POST /api/process   { email_id, inbox_source, sender, subject, body }
                       -> runs the email through the graph, returns the
                          decision, or an "escalated" status if it paused
  POST /api/resume     { email_id, human_response }
                       -> resumes a paused (escalated) run
  GET  /api/health     -> simple liveness check

IMPORTANT - persistence on serverless:
Vercel functions are stateless between invocations (no long-running
process, no in-memory/SQLite state survives). So this uses a real
Postgres-backed checkpointer instead of run_demo.py's InMemorySaver or
run_live.py's local SQLite file - specifically, your Supabase project's
own Postgres database (Supabase is Postgres under the hood). Set
SUPABASE_DB_URL (see README's Vercel section for where to find this) as
an env var / Vercel project secret.
"""
import os
import json

from flask import Flask, request, jsonify
from dotenv import load_dotenv
load_dotenv()

from agent_app.graph.graph import build_graph
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command

app = Flask(__name__)

DB_URL = os.environ.get("SUPABASE_DB_URL")

_RESULT_FIELDS = [
    "category", "sender_type", "decision", "reasoning", "source_used",
    "is_urgent", "urgency_reason", "is_duplicate", "duplicate_reason",
    "draft_reply", "human_response", "final_status",
]


def _clean(result: dict) -> dict:
    return {k: result.get(k) for k in _RESULT_FIELDS if result.get(k) not in (None, False, "")}


def _run_with_graph(fn):
    """Opens a Postgres-backed checkpointer for the duration of one request,
    runs `fn(graph)`, then closes the connection. setup() is idempotent -
    creates the checkpoint tables on first call, no-ops after."""
    if not DB_URL:
        raise RuntimeError(
            "SUPABASE_DB_URL is not set. Add it as a Vercel project env var - "
            "see README's Vercel deployment section for where to find this "
            "connection string in your Supabase project."
        )
    with PostgresSaver.from_conn_string(DB_URL) as checkpointer:
        checkpointer.setup()
        graph = build_graph(checkpointer)
        return fn(graph)


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/api/process", methods=["POST"])
def process_email():
    data = request.get_json(force=True, silent=True) or {}
    required = ["email_id", "inbox_source", "sender", "subject", "body"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"missing required fields: {missing}"}), 400
    data.setdefault("attachments", [])

    def _process(graph):
        config = {"configurable": {"thread_id": data["email_id"]}}
        result = graph.invoke(data, config)
        if "__interrupt__" in result:
            return {"status": "escalated", "interrupt": result["__interrupt__"][0].value}
        return {"status": "completed", "result": _clean(result)}

    try:
        return jsonify(_run_with_graph(_process))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/resume", methods=["POST"])
def resume():
    data = request.get_json(force=True, silent=True) or {}
    email_id = data.get("email_id")
    human_response = data.get("human_response")
    if not email_id or not human_response:
        return jsonify({"error": "email_id and human_response are required"}), 400

    def _resume(graph):
        config = {"configurable": {"thread_id": email_id}}
        result = graph.invoke(Command(resume=human_response), config)
        return {"status": "resumed", "result": _clean(result)}

    try:
        return jsonify(_run_with_graph(_resume))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # Local test server: python api/index.py, then curl localhost:5000/api/health
    app.run(debug=True, port=5000)
