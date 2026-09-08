import re
from collections import defaultdict

def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2}

def select_context(
    observer_state: dict,
    items: list[dict],
    max_items: int,
    max_chars: int,
) -> list[str]:
    """Return refs ranked by weighted semantic relevance and lexical overlap with the current goal."""
    query = _tokens(str(observer_state.get("goal", "")))
    
    # Define edge type weights (higher is more relevant)
    edge_weights = {
        "invalidates": 5,
        "contains_change": 4,
        "rejected_by": 3,
        "evolved_from": 2,
        "available_to": 1,
    }
    
    # Build a mapping from ref to its edge types
    ref_edge_types = defaultdict(list)
    for item in items:
        ref = item["ref"]
        failure_condition = item.get("failure_condition", [])
        if isinstance(failure_condition, list):
            ref_edge_types[ref].extend(failure_condition)
        elif isinstance(failure_condition, str):
            ref_edge_types[ref].append(failure_condition)
    
    # Score each item
    ranked: list[tuple[float, int, str, dict]] = []
    for item in items:
        content_tokens = _tokens(str(item.get("content", "")))
        overlap = len(query & content_tokens) / max(1, len(query | content_tokens))
        
        # Calculate semantic weight from edge types
        semantic_weight = 0
        for edge_type in ref_edge_types[item["ref"]]:
            semantic_weight += edge_weights.get(edge_type, 0)
        
        # Combine lexical overlap with semantic relevance
        final_score = overlap + (semantic_weight * 0.1)
        
        ranked.append((final_score, int(item.get("created_order", 0)), str(item["ref"]), item))
    
    # Sort by score (descending), then by creation order (descending), then by ref
    ranked.sort(key=lambda row: (-row[0], -row[1], row[2]))
    
    selected: list[str] = []
    used_chars = 0
    for _score, _order, ref, item in ranked:
        size = len(str(item.get("content", "")))
        if len(selected) >= max_items:
            break
        if used_chars + size > max_chars:
            continue
        selected.append(ref)
        used_chars += size
    
    return selected
