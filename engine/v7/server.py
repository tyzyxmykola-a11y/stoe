"""
SToE Information Field — API Server
Serves the graph data and navigation endpoints.
"""

from flask import Flask, jsonify, request, send_from_directory
import requests as _req
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
from field import InformationField, CATEGORIES, EDGE_TYPES, OPERATORS
from stoe_coder import get_runtime
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
VERSION = os.getenv("VERSION", "v7")
OLLAMA_URL   = os.getenv("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

app = Flask(__name__, static_folder="static")
field = InformationField(storage_path=os.path.join(os.path.dirname(__file__), "field_data.json"))
coder = get_runtime()

def _coder_local_request():
    origin = request.headers.get("Origin", "")
    local_origin = not origin or origin.startswith("http://127.0.0.1") or origin.startswith("http://localhost")
    return request.remote_addr in {"127.0.0.1", "::1"} and local_origin

# ---- CORS — global handler ----
@app.after_request
def add_cors(response):
    if request.path.startswith("/api/coder/"):
        origin = request.headers.get("Origin", "")
        if not origin or origin.startswith("http://127.0.0.1") or origin.startswith("http://localhost"):
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
    nodes = list(field.nodes.values())
    nodes.sort(key=lambda x: x.get("created_at", x.get("timestamp", "")), reverse=True)
    return jsonify(nodes[:200])

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
    """Edit content and/or category of an existing IP."""
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
    """Hard delete an IP and all its edges."""
    if ip_id not in field.nodes:
        return jsonify({"error": "Not found"}), 404
    del field.nodes[ip_id]
    field.edges = [e for e in field.edges
                   if e["source"] != ip_id and e["target"] != ip_id]
    field.recalc_connections()
    field._save()
    return jsonify({"ok": True})

# ---- CONNECTIONS ----

@app.route("/api/connections", methods=["GET"])
def get_connections():
    """Return all edges with full source/target node data."""
    edges = [e for e in field.edges if not e.get("severed")]
    result = []
    for e in edges:
        result.append({
            **e,
            "source_content": (field.nodes.get(e["source"]) or {}).get("content", "")[:80],
            "target_content": (field.nodes.get(e["target"]) or {}).get("content", "")[:80],
        })
    return jsonify({"connections": result})

@app.route("/api/connections/<edge_id>", methods=["PUT"])
def edit_connection(edge_id):
    """Edit type and/or note of an existing edge."""
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
    """Hard delete an edge."""
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
        source_id=data["source"],
        target_id=data["target"],
        edge_type=data.get("type", "connected_to"),
        weight=data.get("weight", 1.0),
        note=data.get("note", ""),
    )
    # v7: surface the edge id so callers can attach an llm_trace afterward
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
    """
    Topology-aware traversal from ip_id.
    Paper 4 §3.2: returns subgraph within depth hops, edge-type annotated.
    """
    depth = min(int(request.args.get("depth", 2)), 4)
    include_failed = request.args.get("failed", "true") == "true"
    subgraph = field.navigate_from(ip_id, depth=depth, include_failed=include_failed)
    result = sorted(subgraph.values(), key=lambda x: x["depth"])
    return jsonify({"origin": ip_id, "nodes": result, "count": len(result)})

@app.route("/api/navigate/<ip_id>/dead_ends", methods=["GET"])
def navigate_dead_ends(ip_id):
    """
    Paper 4 §5.2: nodes reachable only through failed/contradicted paths.
    """
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
    return jsonify({
        "categories": CATEGORIES,
        "edge_types": EDGE_TYPES,
        "operators": OPERATORS,
        "version": VERSION,
    })

# ---- OPERATOR PERSISTENCE ----

import json as _json

OPERATORS_FILE = os.path.join(os.path.dirname(__file__), "operators_custom.json")

def _load_custom_operators():
    from operators import OPERATOR_TABLE
    defaults = [
        {
            "symbol":      sym,
            "name":        d["name"],
            "description": d["meaning"],
            "prompt":      d["prompt_verb"],
        }
        for sym, d in OPERATOR_TABLE.items()
    ]
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
        return jsonify({"ok": False, "error": "Empty operator list"}), 400
    for op in ops:
        if not op.get("symbol") or not op.get("prompt"):
            return jsonify({"ok": False, "error": f"Operator missing symbol or prompt: {op}"}), 400
    _save_custom_operators(ops)
    return jsonify({"ok": True, "saved": len(ops)})

# ---- SEED DATA ----

@app.route("/api/seed", methods=["POST"])
def seed_data():
    """Load SToE seed from stoe_seed.json. Skips if already seeded."""
    import json as _json

    seed_file = os.path.join(os.path.dirname(__file__), "stoe_seed.json")
    if not os.path.exists(seed_file):
        return jsonify({"ok": False, "error": "stoe_seed.json not found"}), 404

    with open(seed_file, "r", encoding="utf-8") as f:
        seed = _json.load(f)

    seed_nodes = seed.get("nodes", {})
    seed_edges = seed.get("edges", [])

    existing_content = {n["content"].strip().lower() for n in field.nodes.values()}
    existing_ids = set(field.nodes.keys())

    added_nodes, skipped_nodes = 0, 0
    id_map = {}

    for seed_id, node in seed_nodes.items():
        fingerprint = node.get("content", "").strip().lower()
        if fingerprint in existing_content:
            for eid, en in field.nodes.items():
                if en["content"].strip().lower() == fingerprint:
                    id_map[seed_id] = eid
                    break
            skipped_nodes += 1
        else:
            new_id = seed_id if seed_id not in existing_ids else seed_id + "_s"
            field.nodes[new_id] = {**node, "id": new_id}
            existing_content.add(fingerprint)
            existing_ids.add(new_id)
            id_map[seed_id] = new_id
            added_nodes += 1

    existing_edges = {(e["source"], e["target"], e["type"]) for e in field.edges}
    added_edges = 0
    for e in seed_edges:
        src_id = id_map.get(e["source"], e["source"])
        tgt_id = id_map.get(e["target"], e["target"])
        key = (src_id, tgt_id, e["type"])
        if key not in existing_edges and src_id in field.nodes and tgt_id in field.nodes:
            field.edges.append({**e, "source": src_id, "target": tgt_id})
            existing_edges.add(key)
            added_edges += 1

    field.recalc_connections()
    field._save()
    return jsonify({
        "ok": True,
        "added_nodes": added_nodes,
        "skipped_nodes": skipped_nodes,
        "added_edges": added_edges,
        "total_nodes": len(field.nodes),
        "total_edges": len(field.edges)
    })

def _call_llm(prompt):
    """Call local Ollama instance."""
    try:
        r = _req.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": OLLAMA_MODEL, "messages": [{"role": "user", "content": prompt}], "stream": False},
            timeout=300,
        )
        if r.status_code == 200:
            return r.json()["message"]["content"]
        print(f"Ollama error {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"Ollama connection error: {e}")
    return None

def _get_models():
    """List models available in Ollama."""
    try:
        r = _req.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if r.status_code == 200:
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass
    return []

@app.route("/api/recalc", methods=["POST"])
def recalc():
    """Recalculate connection counts for all nodes."""
    field.recalc_connections()
    field._save()
    return jsonify({"ok": True, "nodes": len(field.nodes)})

@app.route("/api/models", methods=["GET"])
def get_models():
    return jsonify({"models": _get_models(), "current": OLLAMA_MODEL, "url": OLLAMA_URL})

@app.route("/api/models/select", methods=["POST", "OPTIONS"])
def select_model():
    global OLLAMA_MODEL
    data = request.json
    OLLAMA_MODEL = data.get("model", OLLAMA_MODEL)
    return jsonify({"model": OLLAMA_MODEL})

OP_MEANING = {
    "+": "combine", "x": "synergy", "-": "remove",
    "r": "evolve", "^": "amplify", "p": "practical", "!": "disrupt"
}

def _clean(text):
    import re
    text = re.sub(r"[*]{1,3}([^*]+)[*]{1,3}", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    preambles = [
        r"^Key Insight:\s*",
        r"^Here.s the key insight:\s*",
        r"^The key insight is:\s*",
        r"^Insight:\s*",
        r"^Summary:\s*",
        r"^Sure[,!]?\s*",
        r"^Certainly[,!]?\s*",
        r"^Of course[,!]?\s*",
        r"^Absolutely[,!]?\s*",
        r"^Great[,!]?\s*",
    ]
    for p in preambles:
        text = re.sub(p, "", text, flags=re.IGNORECASE)
    text = re.sub(r"^[•\-]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[—–\-]+\s*", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def _field_context(seed, idea, max_results=5):
    """Search field with keyword extraction — avoids passing raw questions as queries."""
    import re
    stopwords = {'what','is','are','the','a','an','of','in','and','or','how','why','when','does','do','explain','tell','me','about','can','you'}
    raw = (seed + ' ' + idea).lower()
    raw = re.sub(r'[^a-z0-9 ]', ' ', raw)
    tokens = [t for t in raw.split() if len(t) > 2 and t not in stopwords]
    queries = []
    if tokens:
        queries.append(' '.join(tokens[:4]))
        queries += tokens[:6]
    queries.append(seed[:40])
    seen_ids = set()
    results = []
    for q in queries:
        if not q.strip():
            continue
        try:
            hits = field.search(q.strip())
            for h in hits:
                if h['id'] not in seen_ids:
                    seen_ids.add(h['id'])
                    results.append(h)
                    if len(results) >= max_results:
                        return results
        except Exception:
            pass
    return results

# ============================================================
# v7 — TOPOLOGY-AWARE CONTEXT + PROMPT PREVIEW + TRACE STORE
# ============================================================
# Walks depth-1 neighborhoods of focal IPs and surfaces failed_from /
# contradicts neighbors with explicit tags so the LLM can avoid
# re-attempting dead ends. Both /apply_operator and /context/preview
# route through _build_operator_prompt() so what the preview shows
# is exactly what the model receives.

PRIORITY_EDGE_TYPES = {"failed_from", "contradicts"}

def _topology_context(node_ids, max_per_node=8):
    """Return (neighbors_used, formatted_block) for depth-1 nbhds of node_ids."""
    if not node_ids:
        return [], ""

    lines = []
    neighbors_used = []
    seen = set()

    for nid in node_ids:
        node = field.nodes.get(nid)
        if not node:
            continue

        adj = []
        for e in field.edges:
            if e.get("severed"):
                continue
            if e["source"] == nid:
                adj.append((e, e["target"], "→"))
            elif e["target"] == nid:
                adj.append((e, e["source"], "←"))

        adj.sort(key=lambda x: 0 if x[0]["type"] in PRIORITY_EDGE_TYPES else 1)

        node_label = node.get("name") or node.get("content", "")[:60]
        node_block = [f"\n## {node_label} (id={nid[:8]})"]

        kept = 0
        for edge, other_id, arrow in adj:
            if kept >= max_per_node:
                break
            key = (nid, other_id, edge["type"])
            if key in seen:
                continue
            seen.add(key)
            other = field.nodes.get(other_id)
            if not other:
                continue
            other_label = (other.get("name") or other.get("content", ""))[:80]
            edge_note = (edge.get("note") or "").strip()
            line = f"  [{edge['type']}] {arrow} {other_label}"
            if edge_note:
                line += f" — {edge_note[:140]}"
            node_block.append(line)
            neighbors_used.append({
                "focal_id": nid,
                "neighbor_id": other_id,
                "neighbor_name": other_label[:60],
                "edge_type": edge["type"],
                "edge_note": edge_note[:200],
                "direction": "out" if arrow == "→" else "in",
            })
            kept += 1

        if kept > 0:
            lines.extend(node_block)

    if not lines:
        return [], ""

    formatted = (
        "TOPOLOGY CONTEXT — depth-1 neighborhoods of the focal IPs.\n"
        "[failed_from] and [contradicts] neighbors are surfaced first; "
        "DO NOT re-attempt those dead-ends in your output."
        + "\n".join(lines) + "\n\n"
    )
    return neighbors_used, formatted


def _build_operator_prompt(op, idea, seed, node_ids):
    """
    Build the full LLM prompt for an operator call.
    Returns (prompt, trace_meta) — same path used by /apply_operator and /context/preview.
    """
    ctx_results = _field_context(seed, idea)
    if ctx_results:
        snippets = [f'- {r["content"][:200]}' for r in ctx_results]
        keyword_context = "FIELD KNOWLEDGE (use this, do not use outside knowledge):\n" + "\n".join(snippets) + "\n\n"
    else:
        keyword_context = ""

    topo_neighbors, topo_context = _topology_context(node_ids or [])

    base = f'''{topo_context}{keyword_context}You are reasoning within the Information Field of SToE by Mykola Voronin.
Law of Conservation: no IP vanishes — only loses connections.
Law of Autoinjection: the field contains itself — P↑ := P + (P×P) − F.
Seed context: "{seed}". Be sharp, specific, and think in information points.
'''
    op1 = op[0] if op else "↻"

    custom_ops = _load_custom_operators()
    custom_map = {o["symbol"]: o["prompt"] for o in custom_ops}
    verb = custom_map.get(op1)

    if not verb:
        prompt = base + f"Transform this idea in an interesting direction:\n{idea}"
    elif op1 == "∑":
        # ∑ (Summarize) gets no SToE preamble — pure autoinjective collapse
        prompt = topo_context + keyword_context + verb + "\nIP: " + idea
    else:
        prompt = base + verb + "\nIP: " + idea

    trace_meta = {
        "op": op,
        "model": OLLAMA_MODEL,
        "focal_ids": list(node_ids or []),
        "topology_neighbors": topo_neighbors,
        "keyword_hits": [{"id": r["id"], "content": r["content"][:120]} for r in ctx_results],
        "prompt": prompt,
        "prompt_chars": len(prompt),
        "topology_chars": len(topo_context),
        "keyword_chars": len(keyword_context),
    }
    return prompt, trace_meta


@app.route("/api/apply_operator", methods=["POST"])
def apply_operator():
    data = request.json or {}
    op       = data.get("op", "↻")
    idea     = data.get("idea", "")
    seed     = data.get("seed", "")
    node_ids = data.get("node_ids", []) or []

    prompt, trace = _build_operator_prompt(op, idea, seed, node_ids)
    print(f"[apply_operator] op={op!r} model={OLLAMA_MODEL} "
          f"topo={trace['topology_chars']}c kw={trace['keyword_chars']}c "
          f"focal={len(node_ids)} neighbors={len(trace['topology_neighbors'])}")

    result = _call_llm(prompt)
    if result:
        result = _clean(result)
        from datetime import datetime as _dt2
        trace["response"] = result
        trace["timestamp"] = _dt2.utcnow().isoformat() + "Z"
        return jsonify({
            "result": result,
            "field_hits": len(trace["keyword_hits"]),
            "topology_neighbors": len(trace["topology_neighbors"]),
            "trace": trace,
        })
    return jsonify({"error": f"Ollama call failed — is Ollama running at {OLLAMA_URL}?"})


@app.route("/api/context/preview", methods=["POST", "OPTIONS"])
def context_preview():
    """v7: assemble the exact prompt /apply_operator would build, no LLM call."""
    if request.method == "OPTIONS":
        return "", 200
    data = request.json or {}
    op       = data.get("op", "↻")
    idea     = data.get("idea", "")
    seed     = data.get("seed", "")
    node_ids = data.get("node_ids", []) or []
    _, trace = _build_operator_prompt(op, idea, seed, node_ids)
    return jsonify(trace)


@app.route("/api/trace/<entity_id>", methods=["GET"])
def get_trace(entity_id):
    """v7: fetch llm_trace stored in metadata for any IP or edge."""
    node = field.nodes.get(entity_id)
    if node:
        trace = (node.get("metadata") or {}).get("llm_trace")
        if trace:
            return jsonify({"kind": "ip", "id": entity_id, "trace": trace})
    for e in field.edges:
        if e.get("id") == entity_id:
            trace = (e.get("metadata") or {}).get("llm_trace")
            if trace:
                return jsonify({"kind": "edge", "id": entity_id, "trace": trace})
            break
    return jsonify({"error": "No trace found for this id"}), 404


@app.route("/api/trace/<entity_id>", methods=["PUT", "OPTIONS"])
def put_trace(entity_id):
    """v7: attach an llm_trace to an existing IP or edge's metadata."""
    if request.method == "OPTIONS":
        return "", 200
    trace = (request.json or {}).get("trace")
    if not trace:
        return jsonify({"error": "Body must contain 'trace'"}), 400
    node = field.nodes.get(entity_id)
    if node:
        node.setdefault("metadata", {})["llm_trace"] = trace
        field._save()
        return jsonify({"ok": True, "kind": "ip"})
    for i, e in enumerate(field.edges):
        if e.get("id") == entity_id:
            field.edges[i].setdefault("metadata", {})["llm_trace"] = trace
            field._save()
            return jsonify({"ok": True, "kind": "edge"})
    return jsonify({"error": "Entity not found"}), 404


@app.route("/api/score", methods=["POST"])
def score_idea():
    data = request.json
    idea = data.get("idea", "")
    prompt = f"""Rate this idea on three dimensions.
Respond ONLY with three lines exactly like this:
Novelty: X
Usefulness: X
Feasibility: X
Where X is a number 1-5.

Idea: {idea[:500]}"""
    result = _call_llm(prompt)
    scores = {"Novelty": 5, "Usefulness": 5, "Feasibility": 5}
    if result:
        for line in result.split("\n"):
            if ":" in line:
                try:
                    k, v = line.split(":", 1)
                    k = k.strip()
                    if k in scores:
                        scores[k] = max(1, min(5, int(v.strip())))
                except:
                    pass
    return jsonify({"scores": scores})

# ---- AGENT CHAT ----
@app.route("/api/agent/chat", methods=["POST", "OPTIONS"])
def agent_chat():
    if request.method == "OPTIONS": return "", 200
    data = request.json
    system = data.get("system", "")
    messages = data.get("messages", [])
    try:
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)
        payload = {
            "model": OLLAMA_MODEL,
            "messages": full_messages,
            "stream": False,
            "options": {"num_ctx": 4096}
        }
        print(f"[agent_chat] model={OLLAMA_MODEL} messages={len(full_messages)}")
        r = _req.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=180)
        print(f"[agent_chat] status={r.status_code}")
        if r.status_code == 200:
            result = r.json()["message"]["content"]
            return jsonify({"result": result})
        print(f"[agent_chat] error body: {r.text[:200]}")
        return jsonify({"error": f"Ollama error {r.status_code}: {r.text[:200]}"})
    except Exception as e:
        print(f"[agent_chat] exception: {e}")
        return jsonify({"error": str(e)})

# ---- WIPE ----
@app.route("/api/field/wipe", methods=["POST", "OPTIONS"])
def wipe_field():
    if request.method == "OPTIONS": return "", 200
    field.nodes = {}
    field.edges = []
    field._save()
    return jsonify({"ok": True, "message": "Field wiped"})

@app.route("/api/field/import", methods=["POST", "OPTIONS"])
def import_field():
    if request.method == "OPTIONS": return "", 200
    data = request.json
    if not data or "nodes" not in data or "edges" not in data:
        return jsonify({"ok": False, "error": "Invalid field data — needs nodes and edges"})
    field.nodes = data["nodes"]
    field.edges = data["edges"]
    field._save()
    return jsonify({"ok": True, "nodes": len(field.nodes), "edges": len(field.edges)})

@app.route("/api/field/merge", methods=["POST", "OPTIONS"])
def merge_field():
    """Add new nodes/edges from JSON, skip duplicates by content (case-insensitive strip)."""
    if request.method == "OPTIONS": return "", 200
    data = request.json
    if not data or "nodes" not in data or "edges" not in data:
        return jsonify({"ok": False, "error": "Invalid field data — needs nodes and edges"})

    existing_content = {n["content"].strip().lower() for n in field.nodes.values()}
    existing_ids = set(field.nodes.keys())

    added_nodes = 0
    id_map = {}

    for old_id, node in data["nodes"].items():
        fingerprint = node.get("content", "").strip().lower()
        if fingerprint in existing_content:
            for eid, en in field.nodes.items():
                if en["content"].strip().lower() == fingerprint:
                    id_map[old_id] = eid
                    break
        else:
            new_id = old_id if old_id not in existing_ids else old_id + "_m"
            field.nodes[new_id] = node
            field.nodes[new_id]["id"] = new_id
            existing_content.add(fingerprint)
            existing_ids.add(new_id)
            id_map[old_id] = new_id
            added_nodes += 1

    existing_edges = {(e["source"], e["target"]) for e in field.edges}
    added_edges = 0
    for edge in data.get("edges", []):
        src = id_map.get(edge["source"], edge["source"])
        tgt = id_map.get(edge["target"], edge["target"])
        if (src, tgt) not in existing_edges and src in field.nodes and tgt in field.nodes:
            new_edge = dict(edge)
            new_edge["source"] = src
            new_edge["target"] = tgt
            field.edges.append(new_edge)
            existing_edges.add((src, tgt))
            added_edges += 1

    field._save()
    return jsonify({"ok": True, "added_nodes": added_nodes, "added_edges": added_edges,
                    "total_nodes": len(field.nodes), "total_edges": len(field.edges)})

# ---- FAVICON ----
@app.route("/favicon.ico")
def favicon():
    return "", 204

# ---- STATIC ----

@app.route("/")
def index():
    return send_from_directory(os.path.join(os.path.dirname(__file__), "static"), "index.html")


import json as _json
from datetime import datetime as _dt

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

@app.route("/api/log", methods=["POST", "OPTIONS"])
def write_log():
    if request.method == "OPTIONS": return "", 200
    data = request.json
    entries = data.get("entries", [])
    session_id = data.get("session_id", "unknown")
    if not entries:
        return jsonify({"ok": True})
    filename = f"session_{session_id}.log"
    filepath = os.path.join(LOG_DIR, filename)
    with open(filepath, "a", encoding="utf-8") as f:
        for e in entries:
            f.write(f"[{e.get('ts','')}] [{e.get('level','info').upper()}] {e.get('msg','')}\n")
    return jsonify({"ok": True, "file": filename})

@app.route("/api/log/files", methods=["GET", "OPTIONS"])
def list_log_files():
    try:
        files = sorted(os.listdir(LOG_DIR), reverse=True)[:20]
        result = []
        for fname in files:
            fp = os.path.join(LOG_DIR, fname)
            result.append({"name": fname, "size": os.path.getsize(fp)})
        return jsonify(result)
    except Exception as e:
        return jsonify([])

@app.route("/api/log/files/<filename>", methods=["GET", "OPTIONS"])
def get_log_file(filename):
    from flask import send_from_directory as sfd
    return sfd(LOG_DIR, filename, as_attachment=True)

if __name__ == "__main__":
    print(f"SToE Information Field running at http://localhost:5000")
    print(f"Ollama: {OLLAMA_URL} | Model: {OLLAMA_MODEL}")
    models = _get_models()
    if models:
        print(f"Available models: {', '.join(models)}")
    else:
        print("Warning: Ollama not responding at", OLLAMA_URL)
    app.run(debug=False, port=5000, host="127.0.0.1")
