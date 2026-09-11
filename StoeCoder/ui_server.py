"""
SToE Information Field — API Server
Serves the graph data and navigation endpoints.
"""

from flask import Flask, jsonify, request, send_from_directory
import requests as _req
import os
import sys
from urllib.parse import urlsplit
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
sys.path.insert(0, os.path.dirname(__file__))
from field import InformationField, CATEGORIES, EDGE_TYPES, OPERATORS
from stoe_coder import get_runtime
from event_logging import install_event_logging
VERSION = os.getenv("VERSION", "v7")
OLLAMA_URL   = os.getenv("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

app = Flask(__name__, static_folder="static")
field = InformationField(storage_path=os.path.join(os.path.dirname(__file__), "field_data.json"))
coder = get_runtime()
install_event_logging(coder)

def _local_origin(origin):
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
        return (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                and parsed.username is None and parsed.password is None
                and not parsed.path and not parsed.query and not parsed.fragment
                and (parsed.port is None or 1 <= parsed.port <= 65535))
    except ValueError:
        return False


def _coder_local_request():
    return request.remote_addr in {"127.0.0.1", "::1"} and _local_origin(request.headers.get("Origin", ""))

# ---- CORS — global handler ----
@app.after_request
def add_cors(response):
    if request.path.startswith("/api/coder/"):
        origin = request.headers.get("Origin", "")
        if _local_origin(origin):
            response.headers["Access-Control-Allow-Origin"] = origin or "http://127.0.0.1:5000"
    else:
        response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response

@app.before_request
def handle_options():
    if request.method == "OPTIONS":
        response = app.make_default_options_response()
        if request.path.startswith("/api/coder/") and not _coder_local_request():
            return jsonify({"error": "SToE Coder is localhost-only"}), 403
        response.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        return response

# ---- FIELD ----

def _coder_call(operation):
    if not _coder_local_request():
        return jsonify({"error": "SToE Coder is localhost-only"}), 403
    try:
        return jsonify(operation())
    except (ValueError, RuntimeError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400

@app.route("/api/coder/status", methods=["GET"])
def coder_status():
    return _coder_call(coder.status)

@app.route("/api/coder/events", methods=["GET"])
def coder_events():
    return _coder_call(lambda: coder.events(int(request.args.get("limit", 100))))

@app.route("/api/coder/models", methods=["GET"])
def coder_models():
    return _coder_call(coder.models)

@app.route('/api/coder/roles', methods=['GET'])
def coder_roles():
    return _coder_call(coder.roles.load)

@app.route('/api/coder/roles/save', methods=['POST'])
def coder_role_save():
    data = request.get_json(silent=True) or {}
    return _coder_call(lambda: coder.roles.save(data.get('role'), data.get('original_name')))

@app.route('/api/coder/roles/delete', methods=['POST'])
def coder_role_delete():
    data = request.get_json(silent=True) or {}
    return _coder_call(lambda: coder.roles.delete(data.get('name')))

@app.route("/api/coder/chat", methods=["POST"])
def coder_chat():
    data = request.get_json(silent=True) or {}
    return _coder_call(lambda: coder.chat(data.get("message", "")))

@app.route("/api/coder/task", methods=["POST"])
def coder_task():
    data = request.get_json(silent=True) or {}
    return _coder_call(lambda: coder.submit_task(data.get("objective", ""), allow_commit=bool(data.get("allow_commit")), allow_push=bool(data.get("allow_push")), allowed_paths=data.get("allowed_paths")))

@app.route("/api/coder/git/diff", methods=["GET"])
def coder_git_diff():
    return _coder_call(coder.git_diff)

@app.route("/api/coder/git/commit", methods=["POST"])
def coder_git_commit():
    data = request.get_json(silent=True) or {}
    return _coder_call(lambda: coder.git_commit(data.get("message", "")))

@app.route("/api/coder/git/pull", methods=["POST"])
def coder_git_pull():
    return _coder_call(coder.git_pull)

@app.route("/api/coder/git/push", methods=["POST"])
def coder_git_push():
    return _coder_call(coder.git_push)

@app.route("/api/coder/git/merge", methods=["POST"])
def coder_git_merge():
    return _coder_call(coder.git_merge)

@app.route("/api/coder/stop", methods=["POST"])
def coder_stop():
    return _coder_call(coder.stop)

@app.route("/api/coder/resume", methods=["POST"])
def coder_resume():
    return _coder_call(coder.resume)

@app.route("/api/field", methods=["GET"])
def get_field():
    limit = int(request.args.get("limit", 500))
    return jsonify(field.get_all(limit=limit))

@app.route("/api/stats", methods=["GET"])
def get_stats():
    return jsonify(field.get_stats())

# ---- POINTS ----

def _point_limit(nodes, limit=200):
    values = list(nodes)
    values.sort(key=lambda x: x.get("created_at", x.get("timestamp", "")), reverse=True)
    return values[:limit]

@app.route("/api/points", methods=["GET"])
def get_points():
    category = request.args.get("category")
    session_id = request.args.get("session_id")
    query = request.args.get("q")
    if query:
        return jsonify(field.search(query))
    if category:
        return jsonify(field.get_by_category(category))
    if session_id:
        return jsonify(field.get_by_session(session_id))
    return jsonify(_point_limit(field.nodes.values()))

@app.route("/api/points", methods=["POST"])
def add_point():
    data = request.json
    ip_id = field.add_point(
        content=data.get("content", ""),
        category=data.get("category", "Unknown"),
        ip_type=data.get("type", "imaginary"),
        score=data.get("score"),
        operator=data.get("operator", ""),
        session_id=data.get("session_id", ""),
        metadata=data.get("metadata", {}),
        name=data.get("name", ""),
        description=data.get("description", ""),
        expression=data.get("expression", ""),
    )
    return jsonify({"id": ip_id, "point": field.nodes[ip_id]})

@app.route("/api/points/<ip_id>", methods=["GET"])
def get_point(ip_id):
    ip = field.nodes.get(ip_id)
    if not ip:
        return jsonify({"error": "Not found"}), 404
    adjacent = field.get_adjacent(ip_id)
    return jsonify({"point": ip, "adjacent": adjacent})

@app.route("/api/points/<ip_id>/ghost", methods=["POST"])
def ghost_point(ip_id):
    success = field.ghost(ip_id)
    return jsonify({"success": success})

@app.route("/api/points/<ip_id>", methods=["PUT"])
def edit_point(ip_id):
    ip = field.nodes.get(ip_id)
    if not ip:
        return jsonify({"error": "Not found"}), 404
    data = request.json or {}
    for field_name in ["content","category","type","name","description","expression"]:
        if field_name in data:
            field.nodes[ip_id][field_name] = data[field_name]
    field._save()
    return jsonify({"ok": True, "point": field.nodes[ip_id]})

@app.route("/api/points/<ip_id>", methods=["DELETE"])
def delete_point(ip_id):
    if ip_id not in field.nodes:
        return jsonify({"error": "Not found"}), 404
    del field.nodes[ip_id]
    field.edges = [e for e in field.edges if e["source"] != ip_id and e["target"] != ip_id]
    field.recalc_connections()
    field._save()
    return jsonify({"ok": True})

# ---- CONNECTIONS ----

@app.route("/api/connections", methods=["GET"])
def get_connections():
    edges = [e for e in field.edges if not e.get("severed")]
    result = []
    for e in edges:
        result.append({**e,
                       "source_content": (field.nodes.get(e["source"]) or {}).get("content", "")[:80],
                       "target_content": (field.nodes.get(e["target"]) or {}).get("content", "")[:80]})
    return jsonify({"connections": result})

@app.route("/api/connections/<edge_id>", methods=["PUT"])
def edit_connection(edge_id):
    for i, e in enumerate(field.edges):
        if e["id"] == edge_id:
            data = request.json or {}
            if "type" in data:
                field.edges[i]["type"] = data["type"]
            if "note" in data:
                field.edges[i]["note"] = data["note"]
            if "weight" in data:
                field.edges[i]["weight"] = float(data["weight"])
            field._save()
            return jsonify({"ok": True, "edge": field.edges[i]})
    return jsonify({"error": "Not found"}), 404

@app.route("/api/connections/<edge_id>", methods=["DELETE"])
def delete_connection(edge_id):
    before = len(field.edges)
    field.edges = [e for e in field.edges if e["id"] != edge_id]
    if len(field.edges) == before:
        return jsonify({"error": "Not found"}), 404
    counts = {}
    for e in field.edges:
        if not e.get("severed"):
            counts[e["source"]] = counts.get(e["source"], 0) + 1
            counts[e["target"]] = counts.get(e["target"], 0) + 1
    for ip_id in field.nodes:
        field.nodes[ip_id]["connections"] = counts.get(ip_id, 0)
    field._save()
    return jsonify({"ok": True})

@app.route("/api/connect", methods=["POST"])
def connect():
    data = request.json
    if data.get("source") == data.get("target"):
        return jsonify({"success": False, "error": "Self-loop rejected"}), 400
    success = field.connect(
        source_id=data["source"], target_id=data["target"],
        edge_type=data.get("type", "connected_to"), weight=data.get("weight", 1.0),
        note=data.get("note", ""))
    edge_id = field.edges[-1]["id"] if success and field.edges else None
    return jsonify({"success": success, "edge_id": edge_id})

@app.route("/api/disconnect/<edge_id>", methods=["POST"])
def disconnect(edge_id):
    success = field.disconnect(edge_id)
    return jsonify({"success": success})

# ---- NAVIGATION ----

@app.route("/api/navigate/<ip_id>/adjacent", methods=["GET"])
def navigate_adjacent(ip_id):
    edge_types = request.args.getlist("type")
    include_severed = request.args.get("severed", "false") == "true"
    adjacent = field.get_adjacent(ip_id, edge_types or None, include_severed)
    return jsonify(adjacent)

@app.route("/api/navigate/<ip_id>/topology", methods=["GET"])
def navigate_topology(ip_id):
    depth = min(int(request.args.get("depth", 2)), 4)
    include_failed = request.args.get("failed", "true") == "true"
    subgraph = field.navigate_from(ip_id, depth=depth, include_failed=include_failed)
    result = sorted(subgraph.values(), key=lambda x: x["depth"])
    return jsonify({"origin": ip_id, "nodes": result, "count": len(result)})

@app.route("/api/navigate/<ip_id>/dead_ends", methods=["GET"])
def navigate_dead_ends(ip_id):
    return jsonify(field.dead_end_query(ip_id))

@app.route("/api/navigate/path", methods=["GET"])
def navigate_path():
    source = request.args.get("from")
    target = request.args.get("to")
    path = field.path_query(source, target)
    return jsonify(path)

@app.route("/api/navigate/failed", methods=["GET"])
def navigate_failed():
    ip_id = request.args.get("ip_id")
    return jsonify(field.get_failed_paths(ip_id))

@app.route("/api/navigate/contradictions", methods=["GET"])
def navigate_contradictions():
    return jsonify(field.get_contradictions())

# ---- SESSIONS ----

@app.route("/api/sessions", methods=["GET"])
def get_sessions():
    return jsonify(field.get_sessions())

# ---- META ----

@app.route("/api/meta", methods=["GET"])
def get_meta():
    return jsonify({"categories": CATEGORIES, "edge_types": EDGE_TYPES, "operators": OPERATORS, "version": VERSION})

# ---- OPERATOR PERSISTENCE ----

import json as _json
OPERATORS_FILE = os.path.join(os.path.dirname(__file__), "operators_custom.json")

def _load_custom_operators():
    from operators import OPERATOR_TABLE
    defaults = [{"symbol": sym, "name": d["name"], "description": d["meaning"], "prompt": d["prompt_verb"]}
                for sym, d in OPERATOR_TABLE.items()]
    if not os.path.exists(OPERATORS_FILE):
        return defaults
    try:
        with open(OPERATORS_FILE, "r", encoding="utf-8") as f:
            data = _json.load(f)
        if isinstance(data, list) and data:
            return data
    except Exception:
        pass
    return defaults

def _save_custom_operators(ops_list):
    with open(OPERATORS_FILE, "w", encoding="utf-8") as f:
        _json.dump(ops_list, f, ensure_ascii=False, indent=2)

@app.route("/api/operators", methods=["GET"])
def get_operators():
    return jsonify({"operators": _load_custom_operators()})

@app.route("/api/operators/save", methods=["POST", "OPTIONS"])
def save_operators():
    data = request.json
    ops = data.get("operators", []) if data else []
    if not ops:
        return jsonify({"ok": False, "error": "No operators"}), 400
    _save_custom_operators(ops)
    return jsonify({"ok": True})

@app.route("/api/log", methods=["POST"])
def save_log():
    return jsonify({"ok": True})

@app.route("/api/agent/chat", methods=["POST"])
def agent_chat():
    data = request.json or {}
    return jsonify({"result": field.agent_chat(data.get("system", ""), data.get("messages", []), OLLAMA_URL, OLLAMA_MODEL)})
