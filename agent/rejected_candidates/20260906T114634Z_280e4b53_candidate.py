import re
from collections import defaultdict
from typing import List, Dict, Any

def select_context(
    observer_state: Dict[str, Any],
    items: List[Dict[str, Any]],
    max_items: int,
    max_chars: int
) -> List[str]:
    """
    Select context items based on observer state and item relevance.
    
    Args:
        observer_state: Contains goal, constraints, evidence, questions
        items: Available items with refs, content, origin, kind, outcome, failure_condition
        max_items: Maximum number of items to return
        max_chars: Maximum total character count of selected content
    
    Returns:
        List of unique item refs that meet selection criteria
    """
    # Extract observer information
    goal = str(observer_state.get("goal", ""))
    active_constraints = observer_state.get("active_constraints", [])
    changed_constraints = observer_state.get("changed_constraints", [])
    evidence = observer_state.get("evidence", [])
    open_questions = observer_state.get("open_questions", [])
    
    # Tokenize goal for lexical overlap
    def _tokens(text: str) -> set[str]:
        return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2}
    
    query_tokens = _tokens(goal)
    
    # Score items based on multiple criteria
    scored_items = []
    
    for item in items:
        ref = item["ref"]
        content = str(item.get("content", ""))
        origin = item.get("origin", "")
        kind = item.get("kind", "")
        outcome = item.get("outcome", "")
        failure_condition = item.get("failure_condition", "")
        created_order = int(item.get("created_order", 0))
        
        # Lexical overlap with goal
        content_tokens = _tokens(content)
        overlap = len(query_tokens & content_tokens) / max(1, len(query_tokens | content_tokens))
        
        # Constraint relevance scoring
        constraint_score = 0.0
        
        # Check if item relates to active constraints
        for constraint in active_constraints:
            if constraint.lower() in content.lower():
                constraint_score += 0.3
        
        # Check if item relates to changed constraints
        for constraint in changed_constraints:
            if constraint.lower() in content.lower():
                constraint_score += 0.5
        
        # Check if item relates to evidence
        for ev in evidence:
            if ev.lower() in content.lower():
                constraint_score += 0.2
        
        # Check if item relates to open questions
        for question in open_questions:
            if question.lower() in content.lower():
                constraint_score += 0.2
        
        # Failure condition relevance (only if there are actual failures)
        failure_relevance = 0.0
        if failure_condition and any(constraint.lower() in failure_condition.lower() for constraint in active_constraints + changed_constraints):
            failure_relevance = 0.4
        
        # Origin-based scoring (if origin is relevant to observer role)
        origin_score = 0.0
        if "observer" in origin.lower() or "instantiation" in origin.lower():
            origin_score = 0.3
        
        # Combine scores
        final_score = (
            overlap * 0.4 +
            constraint_score * 0.3 +
            failure_relevance * 0.2 +
            origin_score * 0.1
        )
        
        scored_items.append((final_score, created_order, ref, item))
    
    # Sort by score (descending), then by creation order (descending), then by ref (ascending)
    scored_items.sort(key=lambda x: (-x[0], -x[1], x[2]))
    
    # Select items respecting limits
    selected_refs = []
    used_chars = 0
    
    for score, order, ref, item in scored_items:
        content_size = len(str(item.get("content", "")))
        
        if len(selected_refs) >= max_items:
            break
        
        if used_chars + content_size > max_chars:
            continue
        
        selected_refs.append(ref)
        used_chars += content_size
    
    return selected_refs
