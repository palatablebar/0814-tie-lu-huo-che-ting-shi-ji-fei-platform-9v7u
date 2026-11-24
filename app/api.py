from flask import Blueprint, Response, current_app, jsonify, request

from app.business import DomainIssue
from app.evidence.render import artifact
from app.inputs import read_input
from app.modules.pipeline import run
from app.retention.disputes import close_dispute, list_disputes, open_dispute
from app.retention.render import CONTENT_TYPE, render
from app.retention.service import dispose, get_result
from app.review.service import execute, review

api = Blueprint("api", __name__, url_prefix="/api")
STAGES = {"intake": 1, "prepare": 2, "calculate": 3, "policy": 4, "balance": 5}


def _stores():
    return current_app.extensions["runs"], current_app.extensions["disposals"]


@api.post("/stages/<stage>")
def preview(stage):
    if stage not in STAGES:
        raise DomainIssue("STAGE_UNKNOWN")
    return jsonify(run(read_input(), STAGES[stage]))


@api.route("/runs", methods=["GET", "POST"])
def runs():
    store = current_app.extensions["runs"]
    if request.method == "GET":
        return jsonify(items=store.list())
    return jsonify(execute(store, read_input()))


@api.route("/runs/<run_id>", methods=["GET", "PATCH"])
def batch(run_id):
    store = current_app.extensions["runs"]
    if request.method == "GET":
        return jsonify(store.load(run_id))
    return jsonify(review(store, run_id, request.get_json(silent=True)))


@api.get("/runs/<run_id>/evidence")
def export(run_id):
    report = current_app.extensions["runs"].load(run_id)
    return Response(
        artifact(report),
        mimetype="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="review-{report["id"][:12]}.json"',
            "Cache-Control": "no-store",
        },
    )


# ---- 月末交接处置 ----
def _retention_days():
    value = request.values.get("retention_days")
    return None if value is None or value == "" else value


def _decision_moment():
    body = request.get_json(silent=True)
    if isinstance(body, dict) and "at" in body:
        return body["at"]
    return None


@api.post("/runs/<run_id>/disposal")
def run_disposal(run_id):
    runs, disposals = _stores()
    result = dispose(
        runs, disposals, run_id, _retention_days(), at=_decision_moment()
    )
    return Response(render(result), mimetype=CONTENT_TYPE)


@api.get("/runs/<run_id>/disposal")
def read_disposal(run_id):
    """页面读取：与下载端点序列化同一份处置结果。"""
    _, disposals = _stores()
    result = get_result(disposals, run_id)
    return Response(render(result), mimetype=CONTENT_TYPE)


@api.get("/runs/<run_id>/disposal/download")
def download_disposal(run_id):
    _, disposals = _stores()
    result = get_result(disposals, run_id)
    return Response(
        render(result),
        mimetype=CONTENT_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="disposal-{run_id[:12]}.json"',
            "Cache-Control": "no-store",
        },
    )


@api.get("/disposals")
def all_disposals():
    _, disposals = _stores()
    return jsonify(items=disposals.list_disposals())


# ---- 争议登记 ----
@api.route("/runs/<run_id>/disputes", methods=["GET", "POST"])
def disputes(run_id):
    runs, disposals = _stores()
    if request.method == "GET":
        runs.load(run_id)
        return jsonify(items=list_disputes(disposals, run_id))
    return jsonify(
        open_dispute(runs, disposals, run_id, request.get_json(silent=True))
    )


@api.post("/disputes/<dispute_id>/close")
def resolve_dispute(dispute_id):
    _, disposals = _stores()
    return jsonify(close_dispute(disposals, dispute_id))
