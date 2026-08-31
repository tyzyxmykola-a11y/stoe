"""
SToE v3 Benchmark Grader
========================
Takes an LLM output string and a puzzle dict (from puzzles.json) and decides
pass/fail. Designed to be tolerant of LLM formatting variation while strict
about answer correctness.

Grading protocol
----------------
1. The LLM is instructed to end its response with a line of the form:
       FINAL_ANSWER: <answer in the puzzle's answer_format>
2. The grader extracts everything after the last `FINAL_ANSWER:` token.
3. Normalization is per-format. See `_normalize_*` functions.
4. Returns a `Verdict` with `correct: bool`, `reason: str`, and the
   parsed-and-normalized form of both the LLM answer and the expected.

The grader does NOT call an LLM. It is purely deterministic. This matters
because v3's structural evaluator (slice 3) is also forbidden from using
LLM judgment — keeping the grader LLM-free keeps the benchmark separable
from the scoring loop.

Usage
-----
    from grader import load_puzzles, grade
    puzzles = load_puzzles()
    verdict = grade(puzzles[0], llm_output_string)
    print(verdict.correct, verdict.reason)
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any


PUZZLES_FILE = os.path.join(os.path.dirname(__file__), "puzzles.json")


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class Verdict:
    correct: bool
    reason: str
    extracted: Any = None
    expected: Any = None


def load_puzzles(path: str = PUZZLES_FILE) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["puzzles"]


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

_FINAL_RE = re.compile(r"final[_\s]*answer\s*:\s*(.+?)(?:\n\s*\n|\Z)",
                       re.IGNORECASE | re.DOTALL)

def extract_final_answer(llm_output: str) -> str | None:
    """
    Pull the text after the last `FINAL_ANSWER:` marker.
    Returns None if no marker is present.
    """
    matches = list(_FINAL_RE.finditer(llm_output))
    if not matches:
        return None
    # Last match wins — LLMs sometimes restate
    return matches[-1].group(1).strip()


# ---------------------------------------------------------------------------
# Normalizers (one per answer_format)
# ---------------------------------------------------------------------------

def _normalize_kv_pipe(s: str) -> dict[str, list[str]]:
    """
    'Alice: blue, fish | Bob: green, dog' -> {'alice': ['blue', 'fish'], 'bob': ['green', 'dog']}
    Sorted-tuple values so order within an entity matters but order between
    entities does not.
    """
    out = {}
    for entry in s.split("|"):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        key, _, val = entry.partition(":")
        key = key.strip().lower()
        parts = [p.strip().lower() for p in val.split(",") if p.strip()]
        out[key] = sorted(parts)  # within-entity order ignored
    return out


def _normalize_letter_to_digit(s: str) -> dict[str, str]:
    """
    'D=7,E=5,N=6' -> {'d': '7', 'e': '5', 'n': '6'}
    """
    out = {}
    for pair in re.split(r"[,;]", s):
        pair = pair.strip()
        if "=" not in pair:
            continue
        k, _, v = pair.partition("=")
        k = k.strip().lower()
        v = v.strip()
        if k and v:
            out[k] = v
    return out


def _normalize_kn_list(s: str) -> dict[str, str]:
    """
    'A=knight, B=knave, C=knight' -> {'a': 'knight', 'b': 'knave', 'c': 'knight'}
    Order between entries doesn't matter (it's a dict).
    """
    out = {}
    for pair in re.split(r"[,;]", s):
        pair = pair.strip()
        if "=" not in pair:
            continue
        k, _, v = pair.partition("=")
        k = k.strip().lower()
        v = v.strip().lower()
        # Tolerate "is a knight" / "is knight" etc.
        if "knight" in v:
            v = "knight"
        elif "knave" in v:
            v = "knave"
        else:
            continue
        if k:
            out[k] = v
    return out


def _normalize_single_value(s: str) -> str:
    """
    Pull the first integer if the answer looks numeric, else lowercase-strip.
    """
    s = s.strip()
    m = re.search(r"-?\d+", s)
    if m:
        return m.group(0)
    return s.lower()


_NORMALIZERS = {
    "kv_pipe": _normalize_kv_pipe,
    "letter_to_digit": _normalize_letter_to_digit,
    "kn_list": _normalize_kn_list,
    "single_value": _normalize_single_value,
}


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

def grade(puzzle: dict, llm_output: str) -> Verdict:
    """
    Grade a single LLM output against a puzzle's expected answer.
    Returns a Verdict.
    """
    fmt = puzzle["answer_format"]
    if fmt not in _NORMALIZERS:
        return Verdict(False, f"unknown answer_format: {fmt}")

    extracted_raw = extract_final_answer(llm_output)
    if extracted_raw is None:
        return Verdict(False, "no FINAL_ANSWER marker in output")

    norm = _NORMALIZERS[fmt]
    try:
        got = norm(extracted_raw)
    except Exception as e:
        return Verdict(False, f"normalize failed: {e}", extracted=extracted_raw)

    expected = norm(puzzle["expected_answer"])

    if got == expected:
        return Verdict(True, "match", extracted=got, expected=expected)
    return Verdict(False, "mismatch", extracted=got, expected=expected)


# ---------------------------------------------------------------------------
# Self-check — run on import to catch puzzle-file typos early
# ---------------------------------------------------------------------------

def self_check() -> list[str]:
    """
    Verify each puzzle's expected_answer is parseable by its declared format.
    Returns a list of error strings (empty if all good).
    """
    errors = []
    for p in load_puzzles():
        fmt = p.get("answer_format")
        if fmt not in _NORMALIZERS:
            errors.append(f"{p['id']}: unknown answer_format {fmt!r}")
            continue
        try:
            parsed = _NORMALIZERS[fmt](p["expected_answer"])
            if not parsed and fmt != "single_value":
                errors.append(f"{p['id']}: expected_answer parses to empty {parsed!r}")
        except Exception as e:
            errors.append(f"{p['id']}: parse error {e}")
    return errors


if __name__ == "__main__":
    errs = self_check()
    if errs:
        print("PUZZLE FILE PROBLEMS:")
        for e in errs:
            print("  -", e)
        raise SystemExit(1)

    pz = load_puzzles()
    print(f"loaded {len(pz)} puzzles, all parse cleanly")
    by_cat = {}
    by_diff = {}
    unverified = []
    for p in pz:
        by_cat[p["category"]] = by_cat.get(p["category"], 0) + 1
        by_diff[p.get("difficulty", "?")] = by_diff.get(p.get("difficulty", "?"), 0) + 1
        if not p.get("verified", True):
            unverified.append(p["id"])
    print("by category:", by_cat)
    print("by difficulty:", by_diff)
    if unverified:
        print(f"UNVERIFIED puzzles ({len(unverified)}):", unverified)
