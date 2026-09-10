"""
SToE Information Field — Core Graph Engine ({VERSION})
Persistent, navigatable information storage based on the Special Theory of Everything.
Law: No information point is ever deleted. Only connections are severed.
"""

import json
import os
import uuid
import time
from datetime import datetime
from typing import Optional

try:
    import networkx as nx
    HAS_NX = True
except ImportError:
    HAS_NX = False

FIELD_FILE = "field_data.json"

# Edge types derived from SToE laws
EDGE_TYPES = [
    "generated_by",    # this IP was created from another
    "evolved_from",    # operator ↻ applied
    "amplified_from",  # operator ^ applied
    "synergy_with",    # operator × applied
    "connected_to",    # operator + applied
    "removed_from",    # operator − applied
    "distributed_to",  # operator ÷ applied
    "failed_from",     # attempted connection that failed
    "contradicts",     # logical tension
    "evaluates",       # one IP assesses another
    "confirmed_by",    # evaluation confirmed
    "adjacent_to",     # structural proximity
    "session_of",      # belongs to session
]

# IP categories from SToE Dashboard
CATEGORIES = [
    "Star",
    "Hidden Diamond",
    "Seed",
    "Fertilizer",
    "Mirror",
    "Catalyst",
    "Vampire",
    "Ghost",
    "Echo",
    "Unknown",
]

# Operator symbols — single source of truth lives in operators.py
from operators import SYMBOL_TO_EDGE as OPERATORS


class InformationField:
    """
    The Information Field — a persistent, monotonically growing graph.
    Nothing is ever deleted. Information points only lose connections.
    """

    def __init__(self, storage_path: str = FIELD_FILE):
        self.storage_path = storage_path
        self.nodes = {}   # id -> node data
        self.edges = []   # list of edge dicts
        self._load()

    def _load(self):
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.nodes = data.get("nodes", {})
                self.edges = data.get("edges", [])
            except Exception:
                self.nodes = {}
                self.edges = []
        self.migrate_schema()
        self.recalc_connections()

    def _save(self):
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump({"nodes": self.nodes, "edges": self.edges}, f, ensure_ascii=False, indent=2)

    def migrate_schema(self):
        """Migrate existing nodes to new schema — adds name/description/expression if missing."""
        for ip_id, node in self.nodes.items():
            # name: extract from content (text before ' — ' or first 60 chars)
            if not node.get("name"):
                c = node.get("content", "")
                node["name"] = c.split(" — ")[0][:80] if " — " in c else c[:60]
            # description: from metadata.description or empty
            if not node.get("description"):
                node["description"] = node.get("metadata", {}).get("description", "")
            # expression: from metadata.expr or empty
            if not node.get("expression"):
                node["expression"] = node.get("metadata", {}).get("expr", "")

    def recalc_connections(self):
        """Recount connections for every node from the edges array."""
        counts = {}
        for e in self.edges:
            if not e.get("severed"):
                counts[e["source"]] = counts.get(e["source"], 0) + 1
                counts[e["target"]] = counts.get(e["target"], 0) + 1
        for ip_id in self.nodes:
            self.nodes[ip_id]["connections"] = counts.get(ip_id, 0)

    def add_point(self, content: str, category: str = "Unknown",
                  ip_type: str = "imaginary", score: Optional[dict] = None,
                  operator: str = "", session_id: str = "",
                  metadata: Optional[dict] = None,
                  name: str = "", description: str = "", expression: str = "") -> str:
        """Add an information point. Returns its ID."""
        ip_id = str(uuid.uuid4()).replace("-", "")[:16]
        self.nodes[ip_id] = {
            "id": ip_id,
            "name": name or content[:60],
            "description": description,
            "expression": expression,
            "content": content,
            "category": category,
            "type": ip_type,
            "score": score or {},
            "operator": operator,
            "session_id": session_id,
            "created_at": datetime.now().isoformat(),
            "connections": 0,
            "metadata": metadata or {},
        }
        self._save()
        return ip_id

    def connect(self, source_id: str, target_id: str,
                edge_type: str = "connected_to",
                weight: float = 1.0, note: str = "") -> bool:
        """Create a typed connection between two information points."""
        if source_id not in self.nodes or target_id not in self.nodes:
            return False
        edge = {
            "id": str(uuid.uuid4()).replace("-", "")[:16],
            "source": source_id,
            "target": target_id,
            "type": edge_type,
            "weight": weight,
            "note": note,
            "created_at": datetime.now().isoformat(),
        }
        self.edges.append(edge)
        # Update connection counts
        self.nodes[source_id]["connections"] = self.nodes[source_id].get("connections", 0) + 1
        self.nodes[target_id]["connections"] = self.nodes[target_id].get("connections", 0) + 1
        self._save()
        return True

    def disconnect(self, edge_id: str) -> bool:
        """
        Disconnect (not delete) an edge.
        The information points remain — only the connection is severed.
        Law: information is conserved.
        """
        for i, e in enumerate(self.edges):
            if e["id"] == edge_id:
                self.edges[i]["severed"] = True
                self.edges[i]["severed_at"] = datetime.now().isoformat()
                self._save()
                return True
        return False

    def ghost(self, ip_id: str) -> bool:
        """
        Mark an IP as Ghost — disconnected but still present.
        Never deleted. SToE law: information is conserved.
        """
        if ip_id in self.nodes:
            self.nodes[ip_id]["category"] = "Ghost"
            self.nodes[ip_id]["ghosted_at"] = datetime.now().isoformat()
            self._save()
            return True
        return False

    # ---- NAVIGATION ----

    def get_adjacent(self, ip_id: str, edge_types: list = None, include_severed: bool = False) -> list:
        """Get all IPs structurally adjacent to this one."""
        adjacent = []
        for e in self.edges:
            if e.get("severed") and not include_severed:
                continue
            if edge_types and e["type"] not in edge_types:
                continue
            if e["source"] == ip_id and e["target"] in self.nodes:
                adjacent.append({
                    "ip": self.nodes[e["target"]],
                    "edge": e,
                    "direction": "outgoing"
                })
            elif e["target"] == ip_id and e["source"] in self.nodes:
                adjacent.append({
                    "ip": self.nodes[e["source"]],
                    "edge": e,
                    "direction": "incoming"
                })
        return adjacent

    def get_failed_paths(self, ip_id: str = None) -> list:
        """Get all failed/ghost information points — conserved dead ends."""
        ghosts = [n for n in self.nodes.values() if n.get("category") == "Ghost"]
        failed_edges = [e for e in self.edges if e["type"] == "failed_from"]
        results = []
        for e in failed_edges:
            if ip_id and e["source"] != ip_id and e["target"] != ip_id:
                continue
            src = self.nodes.get(e["source"])
            tgt = self.nodes.get(e["target"])
            if src and tgt:
                results.append({"from": src, "to": tgt, "edge": e})
        return results

    def find_path(self, source_id: str, target_id: str) -> list:
        """Find structural path between two information points."""
        if not HAS_NX:
            return []
        G = nx.DiGraph()
        for ip_id, ip in self.nodes.items():
            G.add_node(ip_id)
        for e in self.edges:
            if not e.get("severed"):
                G.add_edge(e["source"], e["target"], type=e["type"])
        try:
            path = nx.shortest_path(G, source_id, target_id)
            return [self.nodes[p] for p in path if p in self.nodes]
        except Exception:
            return []

    def search(self, query: str, limit: int = 20) -> list:
        """
        Topology-aware search — combines content relevance with structural
        position in the graph. Scores each IP on:
          - content match (keyword presence, recency)
          - structural centrality (connection count)
          - category weight (Stars/Catalysts ranked higher)
        Returns results ordered by composite score, not just timestamp.
        """
        q = query.lower().strip()
        tokens = [t for t in q.split() if len(t) > 1]
        CAT_WEIGHT = {
            "Star": 5, "Catalyst": 4, "Hidden Diamond": 3,
            "Seed": 2, "Fertilizer": 2, "Mirror": 1,
            "Echo": 1, "Vampire": 0, "Ghost": 0, "Unknown": 0,
        }
        import time as _time
        now = _time.time()
        scored = []
        for ip in self.nodes.values():
            content_lower = ip["content"].lower()
            # Content score: full phrase match beats token matches
            if q and q in content_lower:
                content_score = 10
            else:
                content_score = sum(2 for t in tokens if t in content_lower)
            if content_score == 0:
                continue
            # Recency score: decay over 7 days
            # created_at is ISO string; timestamp is legacy float
            ts = ip.get("timestamp")
            if not ts:
                try:
                    from datetime import datetime as _dt
                    ts = _dt.fromisoformat(ip["created_at"]).timestamp() if ip.get("created_at") else now
                except Exception:
                    ts = now
            age_days = (now - ts) / 86400
            recency = max(0, 1 - age_days / 7)
            # Structural score: connection count (capped)
            conn = min(ip.get("connections", 0), 10)
            # Category weight
            cat_w = CAT_WEIGHT.get(ip.get("category", "Unknown"), 0)
            composite = content_score * 3 + recency * 2 + conn * 1.5 + cat_w
            scored.append((composite, ip))
        scored.sort(key=lambda x: -x[0])
        return [ip for _, ip in scored[:limit]]

    def navigate_from(self, ip_id: str, depth: int = 2,
                      include_failed: bool = True,
                      include_severed: bool = False) -> dict:
        """
        Topology-aware traversal from a starting node.
        Returns the subgraph reachable within `depth` hops,
        annotated with structural role of each edge.
        Paper 4 §3.2: 'navigation that understands connection structure,
        not merely content similarity.'
        """
        visited = {}   # ip_id -> {ip, depth, edges_in}
        frontier = [ip_id]
        for d in range(depth):
            next_frontier = []
            for nid in frontier:
                if nid in visited:
                    continue
                if nid not in self.nodes:
                    continue
                adj = self.get_adjacent(nid, include_severed=include_severed)
                visited[nid] = {
                    "ip": self.nodes[nid],
                    "depth": d,
                    "edges": []
                }
                for item in adj:
                    edge = item["edge"]
                    if not include_failed and edge["type"] == "failed_from":
                        continue
                    visited[nid]["edges"].append({
                        "type": edge["type"],
                        "direction": item["direction"],
                        "target_id": item["ip"]["id"],
                        "weight": edge.get("weight", 1.0),
                        "note": edge.get("note", ""),
                    })
                    next_frontier.append(item["ip"]["id"])
            frontier = [n for n in next_frontier if n not in visited]
        return visited

    def dead_end_query(self, ip_id: str) -> list:
        """
        Paper 4 §5.2: 'what nodes are reachable only through paths
        that have been marked as failed or contradicted?'
        Returns conserved but currently disconnected neighbours of ip_id.
        """
        results = []
        for e in self.edges:
            if e["type"] not in ("failed_from", "contradicts"):
                continue
            other_id = None
            if e["source"] == ip_id:
                other_id = e["target"]
            elif e["target"] == ip_id:
                other_id = e["source"]
            if other_id and other_id in self.nodes:
                results.append({
                    "ip": self.nodes[other_id],
                    "edge_type": e["type"],
                    "edge_id": e["id"],
                    "note": e.get("note", ""),
                })
        return results

    def path_query(self, source_id: str, target_id: str,
                   include_edge_types: bool = True) -> dict:
        """
        Paper 4 §5.2: 'given two nodes, what paths exist between them
        and what edge types do those paths traverse?'
        Returns path with full edge-type annotation.
        """
        if not HAS_NX:
            # Fallback BFS when networkx unavailable
            return self._bfs_path(source_id, target_id)
        G = nx.DiGraph()
        for ip_id in self.nodes:
            G.add_node(ip_id)
        for e in self.edges:
            if not e.get("severed"):
                G.add_edge(e["source"], e["target"],
                           type=e["type"], edge_id=e["id"],
                           weight=e.get("weight", 1.0))
        try:
            path_ids = nx.shortest_path(G, source_id, target_id)
            steps = []
            for i in range(len(path_ids) - 1):
                src, tgt = path_ids[i], path_ids[i+1]
                edge_data = G.get_edge_data(src, tgt, {})
                steps.append({
                    "from": self.nodes.get(src, {"id": src}),
                    "to": self.nodes.get(tgt, {"id": tgt}),
                    "edge_type": edge_data.get("type", "connected_to"),
                    "weight": edge_data.get("weight", 1.0),
                })
            return {"found": True, "length": len(steps), "steps": steps}
        except Exception:
            return {"found": False, "steps": []}

    def _bfs_path(self, source_id: str, target_id: str) -> dict:
        """BFS fallback path-finder (no networkx)."""
        from collections import deque
        q = deque([(source_id, [source_id])])
        visited = {source_id}
        edge_map = {}  # (src,tgt) -> edge
        for e in self.edges:
            if not e.get("severed"):
                edge_map[(e["source"], e["target"])] = e
        while q:
            node, path = q.popleft()
            if node == target_id:
                steps = []
                for i in range(len(path)-1):
                    s, t = path[i], path[i+1]
                    e = edge_map.get((s,t), {})
                    steps.append({
                        "from": self.nodes.get(s, {"id": s}),
                        "to": self.nodes.get(t, {"id": t}),
                        "edge_type": e.get("type", "connected_to"),
                        "weight": e.get("weight", 1.0),
                    })
                return {"found": True, "length": len(steps), "steps": steps}
            for e in self.edges:
                if e.get("severed"):
                    continue
                nxt = None
                if e["source"] == node:
                    nxt = e["target"]
                elif e["target"] == node:
                    nxt = e["source"]
                if nxt and nxt not in visited:
                    visited.add(nxt)
                    q.append((nxt, path + [nxt]))
        return {"found": False, "steps": []}

    def get_by_category(self, category: str) -> list:
        """Get all IPs of a given dashboard category."""
        return [ip for ip in self.nodes.values() if ip["category"] == category]

    def get_by_session(self, session_id: str) -> list:
        """Get all IPs from a specific engine session."""
        return [ip for ip in self.nodes.values() if ip.get("session_id") == session_id]

    def get_sessions(self) -> list:
        """Get all unique session IDs."""
        sessions = {}
        for ip in self.nodes.values():
            sid = ip.get("session_id", "")
            if sid and sid not in sessions:
                sessions[sid] = {
                    "id": sid,
                    "created_at": ip["created_at"],
                    "count": 0
                }
            if sid:
                sessions[sid]["count"] += 1
        return sorted(sessions.values(), key=lambda x: x["created_at"], reverse=True)

    def get_contradictions(self) -> list:
        """Get all contradiction edges — tensions in the field."""
        return [e for e in self.edges if e["type"] == "contradicts"]

    def get_stats(self) -> dict:
        """Field statistics."""
        cats = {}
        for ip in self.nodes.values():
            c = ip.get("category", "Unknown")
            cats[c] = cats.get(c, 0) + 1
        severed = sum(1 for e in self.edges if e.get("severed"))
        return {
            "total_points": len(self.nodes),
            "total_connections": len(self.edges),
            "severed_connections": severed,
            "active_connections": len(self.edges) - severed,
            "sessions": len(self.get_sessions()),
            "categories": cats,
            "ghosts": cats.get("Ghost", 0),
            "stars": cats.get("Star", 0),
        }

    def get_all(self, limit: int = 500) -> dict:
        """Get full field snapshot for visualization."""
        nodes = list(self.nodes.values())
        nodes.sort(key=lambda x: x.get("created_at", x.get("timestamp", "")), reverse=True)
        return {
            "nodes": nodes[:limit],
            "edges": [e for e in self.edges if not e.get("severed")][-1000:],
            "stats": self.get_stats(),
        }

    def add_session_point(self, session_id: str) -> str:
        """Add a session root information point."""
        return self.add_point(
            content=f"Session {session_id}",
            category="Seed",
            ip_type="imaginary",
            session_id=session_id,
            metadata={"is_session_root": True}
        )
