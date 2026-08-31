"""
SToE Engine v2 — Integrated with Information Field ({VERSION})
===================================================
All operator logic is imported from operators.py (single source of truth).
Nothing is redefined here.

Law: Every idea generated is conserved. No path is discarded.
"""

import requests
import os
import time
import sys
from datetime import datetime
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))

from field import InformationField
from operators import (
    OPERATOR_TABLE,
    SYMBOL_TO_EDGE,
    SYMBOL_TO_NAME,
    NUMERIC_TO_SYMBOL,
    VALID_SYMBOLS,
    MODES,
    parse_numeric_ops,
    build_operator_prompt,
    operator_menu_lines,
    modes_menu_lines,
)

load_dotenv()
VERSION = os.getenv("VERSION", "v82")
OLLAMA_URL   = os.getenv("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

# ---------------------------------------------------------------------------
# Persistent field + session
# ---------------------------------------------------------------------------
field      = InformationField(
    storage_path=os.path.join(os.path.dirname(__file__), "field_data.json")
)
SESSION_ID  = datetime.now().strftime('%Y%m%d_%H%M%S')
OUTPUT_FILE = f"output_{SESSION_ID}.txt"


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def log(text: str):
    with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
        f.write(text + "\n")

def log_and_print(text: str):
    print(text)
    log(text)


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

def call_llm(prompt: str) -> tuple[str, float]:
    start = time.time()
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model":    OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream":   False,
            },
            timeout=300,
        )
        if r.status_code == 200:
            return r.json()["message"]["content"], time.time() - start
        print(f"Ollama error {r.status_code}")
    except Exception as e:
        print(f"Ollama error: {e}")
    return "⚠️ API failed", 0


# ---------------------------------------------------------------------------
# Operator application — uses operators.py exclusively
# ---------------------------------------------------------------------------

def apply_operator(op_symbol: str, idea: str, seed: str) -> tuple[str, float]:
    """Apply one SToE operator to an idea. Prompt built by operators.py."""
    prompt = build_operator_prompt(op_symbol, idea, seed)
    return call_llm(prompt)


# ---------------------------------------------------------------------------
# Scoring + classification
# ---------------------------------------------------------------------------

_SCORE_PROMPT = (
    "Rate this idea on three dimensions.\n"
    "Respond ONLY with three lines exactly like this:\n"
    "Novelty: X\nUsefulness: X\nFeasibility: X\n"
    "Where X is a number 1-5.\n\nIdea: {idea}"
)

def score_step(idea: str) -> tuple[dict, int]:
    r, _ = call_llm(_SCORE_PROMPT.format(idea=idea))
    scores = {"Novelty": 5, "Usefulness": 5, "Feasibility": 5}
    for line in r.split("\n"):
        if ":" in line:
            try:
                k, v = line.split(":", 1)
                k = k.strip()
                if k in scores:
                    scores[k] = int(v.strip())
            except Exception:
                pass
    return scores, sum(scores.values())

_CATEGORY_THRESHOLDS = [(14, "Star"), (12, "Catalyst"), (10, "Seed"), (8, "Hidden Diamond")]

def classify_category(score_total: int, content: str) -> str:
    for threshold, category in _CATEGORY_THRESHOLDS:
        if score_total >= threshold:
            return category
    if "repeat" in content.lower() or "again" in content.lower():
        return "Echo"
    if score_total < 5:
        return "Vampire"
    return "Unknown"


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------

def check_for_echoes(seed: str) -> list:
    existing = field.search(seed[:30], limit=5)
    if existing:
        print(f"\n🔍 Found {len(existing)} related information points in field:")
        for ip in existing[:3]:
            print(f"   [{ip['category']}] {ip['content'][:60]}... (session: {ip.get('session_id','-')})")
        print()
    return existing

def conserve_failed(prev_ip_id: str, step_label: str, op_symbol: str) -> str:
    """Ghost a failed step — information is never lost."""
    failed_id = field.add_point(
        content=f"[FAILED] {step_label} op:{op_symbol}",
        category="Ghost", operator=op_symbol,
        session_id=SESSION_ID, metadata={"failed": True},
    )
    field.connect(prev_ip_id, failed_id, edge_type="failed_from")
    print("  ⚠️ API failed — conserved as Ghost in field")
    return failed_id


# ---------------------------------------------------------------------------
# Operator selection UI
# ---------------------------------------------------------------------------

def select_operators(header: str = "") -> list[str]:
    """Interactive menu. Returns list of operator symbols."""
    if header:
        print(header)
    print("\n  Preset modes:")
    for line in modes_menu_lines():
        print(line)
    print("\n  Individual operators:")
    for line in operator_menu_lines():
        print(line)

    raw = input("\nPreset number OR operator codes (e.g. 5,6,7) [default=5,6,7]: ").strip()

    if raw in MODES:
        name, ops = MODES[raw]
        print(f"  → {name}: {' '.join(ops)}")
        extra = input("  Add more? (optional, e.g. 1,2): ").strip()
        if extra:
            ops = ops + parse_numeric_ops(extra)
        return ops

    ops = parse_numeric_ops(raw)
    if not ops:
        ops = ["↻", "^", "!"]
        print(f"  → defaulting to {' '.join(ops)}")
    return ops


# ---------------------------------------------------------------------------
# IDEA MODE
# ---------------------------------------------------------------------------

def run_idea_mode(session_ip_id: str):
    seed = input("\nEnter seed idea: ").strip()
    log(f"[SEED] {seed}")

    related    = check_for_echoes(seed)
    seed_ip_id = field.add_point(
        content=seed, category="Seed",
        session_id=SESSION_ID, metadata={"is_seed": True},
    )
    field.connect(session_ip_id, seed_ip_id, edge_type="generated_by")
    for rel in related[:2]:
        field.connect(seed_ip_id, rel["id"], edge_type="adjacent_to",
                      note="related seed from previous session")

    print("\n1 FAST  |  2 RECURSIVE")
    thinking = input("Thinking mode: ").strip()

    if thinking == "1":
        result, _ = call_llm(f"Improve this idea sharply:\n{seed}")
        log_and_print("\n⚡ FAST RESULT:\n" + result)
        scores, total = score_step(result)
        rid = field.add_point(
            content=result, category=classify_category(total, result),
            score=scores, operator="fast", session_id=SESSION_ID,
        )
        field.connect(seed_ip_id, rid, edge_type="generated_by")
        return

    mode_ops  = select_operators("\n── Operator selection ──")
    iterations = len(mode_ops)

    log_and_print(f"\n=== SEED ===\n{seed}")
    log_and_print(f"OPERATOR PATH: {' '.join(mode_ops)}")
    log_and_print(f"Field has {len(field.nodes)} conserved information points\n")

    current    = seed
    prev_ip_id = seed_ip_id
    best_score = -1
    best_idea  = ""
    best_ip_id = None
    total_model_time = 0

    for i, op in enumerate(mode_ops):
        step_start = time.time()
        log_and_print(f"\n{'─'*40}")
        log_and_print(f"STEP {i+1} | {op}  {SYMBOL_TO_NAME.get(op, '?')}")

        result, t = apply_operator(op, current, seed)
        total_model_time += t

        if result == "⚠️ API failed":
            prev_ip_id = conserve_failed(prev_ip_id, f"Step {i+1}", op)
            continue

        scores, total = score_step(result)
        step_time = time.time() - step_start
        category  = classify_category(total, result)

        log_and_print(f"\nRESULT:\n{result}")
        log_and_print(f"SCORE: {scores} | TOTAL={total} | CATEGORY: {category}")
        log_and_print(f"TIME: {round(step_time, 2)}s")

        ip_id = field.add_point(
            content=result, category=category, score=scores,
            operator=op, session_id=SESSION_ID,
            metadata={"step": i+1, "step_time": step_time},
        )
        field.connect(prev_ip_id, ip_id,
                      edge_type=SYMBOL_TO_EDGE.get(op, "generated_by"),
                      weight=total / 15.0,
                      note=f"Step {i+1}, score {total}")

        if total < best_score - 3 and best_ip_id:
            field.connect(ip_id, best_ip_id, edge_type="contradicts",
                          note="lower quality than previous best")

        prev_ip_id = ip_id
        current    = result

        if total > best_score:
            best_score = total
            best_idea  = result
            best_ip_id = ip_id

    log_and_print("\n" + "="*40 + "\nFINAL SYNTHESIS")
    final, t = call_llm(
        f"Summarize the best version of this idea clearly and powerfully:\n{best_idea}"
    )
    total_model_time += t
    log_and_print(f"\n🌟 BEST IDEA:\n{final}")

    final_id = field.add_point(
        content=final,
        category="Star" if best_score >= 12 else "Hidden Diamond",
        session_id=SESSION_ID,
        metadata={"is_final": True, "best_score": best_score},
    )
    if best_ip_id:
        field.connect(best_ip_id, final_id, edge_type="evolved_from",
                      note="final synthesis")
    field.connect(session_ip_id, final_id, edge_type="evaluates",
                  note="session best output")

    log_and_print(f"\n⏱ MODEL TIME: {round(total_model_time, 2)}s")


# ---------------------------------------------------------------------------
# QUESTION MODE
# ---------------------------------------------------------------------------

def run_question_mode(session_ip_id: str):
    print("\n" + "="*50)
    print("QUESTION MODE — answers populate the field")
    print("Type 'done' to finish, 'review' to see field summary")
    print("="*50 + "\n")

    mode_ops   = select_operators("── Choose operators ──")
    iterations = max(1, int(
        input("Operator iterations per question [3]: ").strip() or "3"
    ))
    mode_ops = (mode_ops * iterations)[:iterations]

    question_count   = 0
    prev_question_id = session_ip_id

    while True:
        print(f"\n{'─'*40}")
        question = input("Question (or 'done' / 'review'): ").strip()

        if question.lower() == "done":
            break

        if question.lower() == "review":
            stats = field.get_stats()
            print(f"\n📊 Field: {stats['total_points']} IPs | "
                  f"{stats['active_connections']} connections | "
                  f"{stats['stars']} stars | {stats['ghosts']} ghosts")
            for cat, count in sorted(stats.get("categories", {}).items(),
                                     key=lambda x: -x[1]):
                print(f"   {cat}: {count}")
            continue

        if not question:
            continue

        question_count += 1
        log(f"\n[Q{question_count}] {question}")
        print(f"\n🔍 Exploring: {question}")

        related = field.search(question[:40], limit=3)
        if related:
            print(f"   ↳ Found {len(related)} related points in field")

        q_ip_id = field.add_point(
            content=f"Q: {question}", category="Seed", operator="?",
            session_id=SESSION_ID,
            metadata={"is_question": True, "question_num": question_count},
        )
        field.connect(prev_question_id, q_ip_id, edge_type="connected_to",
                      note=f"question {question_count}")
        for rel in related[:2]:
            field.connect(q_ip_id, rel["id"], edge_type="adjacent_to",
                          note="related existing point")

        current    = question
        prev_ip_id = q_ip_id
        best_score = -1
        best_ip_id = q_ip_id

        for i, op in enumerate(mode_ops):
            print(f"\n  Step {i+1} [{op}] {SYMBOL_TO_NAME.get(op, '?')}...")

            result, _ = apply_operator(op, current, question)

            if result == "⚠️ API failed":
                prev_ip_id = conserve_failed(
                    prev_ip_id, f"Q{question_count} step {i+1}", op)
                continue

            scores, total = score_step(result)
            category      = classify_category(total, result)

            print(f"  → [{category}] score:{total} | "
                  f"{result[:80]}{'...' if len(result) > 80 else ''}")
            log(f"[Q{question_count}][Step {i+1}][{op}] score:{total}\n{result}\n")

            ip_id = field.add_point(
                content=result, category=category, score=scores,
                operator=op, session_id=SESSION_ID,
                metadata={"question": question, "step": i+1,
                          "question_num": question_count},
            )
            field.connect(prev_ip_id, ip_id,
                          edge_type=SYMBOL_TO_EDGE.get(op, "generated_by"),
                          weight=total / 15.0)

            if total > best_score:
                best_score = total
                best_ip_id = ip_id

            prev_ip_id = ip_id
            current    = result

        if best_ip_id != q_ip_id:
            field.connect(q_ip_id, best_ip_id, edge_type="evaluates",
                          note="best answer to question")

        prev_question_id = q_ip_id
        print(f"\n  ✓ Conserved {len(mode_ops)} iterations for Q{question_count}")

    print(f"\n{'='*40}")
    print(f"Questions explored: {question_count}")
    print(f"Field now has: {len(field.nodes)} information points")
    print("View at: http://localhost:5000")


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

def run():
    total_start = time.time()
    log(f"===== SESSION {SESSION_ID} =====")

    print(f"\n{'='*50}")
    print(f"SToE Engine {VERSION} — Information Field Active")
    print(f"Session : {SESSION_ID}")
    print(f"Field   : {len(field.nodes)} information points stored")
    print(f"{'='*50}\n")

    session_ip_id = field.add_session_point(SESSION_ID)

    print("1 IDEA MODE  |  2 QUESTION MODE")
    engine_mode = input("Engine mode: ").strip()

    if engine_mode == "2":
        run_question_mode(session_ip_id)
    else:
        run_idea_mode(session_ip_id)

    total_time = time.time() - total_start
    log_and_print(f"\n⏱ TOTAL: {round(total_time, 2)}s")
    log_and_print(f"💾 Field now has {len(field.nodes)} conserved information points")
    log_and_print(f"📁 Output saved to {OUTPUT_FILE}")
    log_and_print("🌐 View field at http://localhost:5000")


if __name__ == "__main__":
    run()
