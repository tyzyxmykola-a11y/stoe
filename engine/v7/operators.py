"""
SToE Operator Registry — Single Source of Truth ({VERSION})
================================================
All operator definitions live here. field.py and engine_v2.py import from
this module. Nothing is redefined elsewhere.

Canonical operator table (from SToE papers + prompt):

  Symbol  | Key    | Name           | Meaning
  --------|--------|----------------|------------------------------
  +       | ADD    | Connection     | Join two IPs in co-presence
  −       | SUB    | Removal        | Remove influence / isolate
  ×       | MUL    | Synergy        | Create amplified emergent IP
  ÷       | DIV    | Distribution   | Spread A through context of B
  ↻       | REC    | Recursion      | Self-apply for iterative growth
  ^       | AMP    | Amplification  | Aggressive resonance escalation
  ∅       | NULL   | Null / Void    | Pure absence / baseline
  !       | DIS    | Disruption     | Challenge / break assumptions
  ∑       | SUM    | Summarize      | Autoinjective collapse to core IP
"""

# ---------------------------------------------------------------------------
# OPERATOR TABLE
# Each entry is the single authoritative definition for one operator.
# ---------------------------------------------------------------------------

OPERATOR_TABLE = {
    "+": {
        "key":       "ADD",
        "symbol":    "+",
        "name":      "Connection",
        "meaning":   "Join two IPs in co-presence; both remain intact",
        "prompt_verb": "CONNECTION OPERATOR — do NOT summarize or analyze.\nFind one specific, non-obvious idea that connects directly to this input. Both ideas must remain intact and distinct. Name the connection explicitly — what bridges them? No preamble. No 'I will'. Start directly with the connected idea:",
        "edge_type": "connected_to",
        "numeric":   "1",
        "color":     "Red and blue placed side by side — both intact",
    },
    "−": {
        "key":       "SUB",
        "symbol":    "−",
        "name":      "Removal",
        "meaning":   "Remove weak parts or isolate the core",
        "prompt_verb": "REMOVAL OPERATOR — do NOT summarize or add new ideas.\nStrip everything non-essential from this input. Cut filler, hedging, and repetition. What is the irreducible core — the single IP that remains when everything weak is removed? No preamble. No 'I will'. Output only the sharpened core:",
        "edge_type": "removed_from",
        "numeric":   "2",
        "color":     "Removing blue from purple — only red remains",
    },
    "×": {
        "key":       "MUL",
        "symbol":    "×",
        "name":      "Synergy",
        "meaning":   "Create an amplified emergent IP from two inputs",
        "prompt_verb": "SYNERGY OPERATOR — do NOT summarize either input.\nCollide this idea with itself at full force. What entirely new entity emerges from that collision — something that did not exist in either input alone? Name it precisely. No preamble. No 'I will'. Start directly with the emergent entity:",
        "edge_type": "synergy_with",
        "numeric":   "3",
        "color":     "Blue into yellow makes green — a new entity",
    },
    "÷": {
        "key":       "DIV",
        "symbol":    "÷",
        "name":      "Distribution",
        "meaning":   "Spread A through the context/shape of B",
        "prompt_verb": "DISTRIBUTION OPERATOR — do NOT explain or analyze.\nTake the core of this idea and spread it across 3 completely different real-world contexts. Each context must transform the idea — not just apply it. No preamble. No 'I will'. Start directly with context 1:",
        "edge_type": "distributed_to",
        "numeric":   "4",
        "color":     "Spreading paint through a stencil — shape defines spread",
    },
    "↻": {
        "key":       "REC",
        "symbol":    "↻",
        "name":      "Recursion",
        "meaning":   "Self-apply iteratively; evolve through cycles",
        "prompt_verb": "RECURSION OPERATOR — do NOT summarize or repeat. Take this idea and evolve it one level deeper — apply it to itself, find what it generates when it consumes its own output. No preamble. No 'Recursive Cycle N'. Start directly with the evolved idea:",
        "edge_type": "evolved_from",
        "numeric":   "5",
        "color":     "A spiral — each loop builds on the previous",
    },
    "^": {
        "key":       "AMP",
        "symbol":    "^",
        "name":      "Amplification",
        "meaning":   "Aggressive resonance escalation; self-multiply",
        "prompt_verb": "AMPLIFICATION OPERATOR — do NOT summarize, analyze, or repeat what was said.\nExtract the single sharpest insight from the input and push it to its absolute maximum intensity.\nOne insight only. Make it bolder, more extreme, more specific. No preamble. No 'I will' or 'Let me'. Start directly with the amplified insight:",
        "edge_type": "amplified_from",
        "numeric":   "6",
        "color":     "Feedback loop doubling on itself",
    },
    "!": {
        "key":       "DIS",
        "symbol":    "!",
        "name":      "Disruption",
        "meaning":   "Challenge assumptions; break the frame",
        "prompt_verb": "DISRUPTION OPERATOR — do NOT summarize, analyze, or continue the previous idea.\nIdentify the single biggest hidden assumption in the input and shatter it.\nState what everyone believes, then prove it wrong with a sharp counter-claim. No preamble. No 'I will' or 'Based on'. Start directly with the disruption:",
        "edge_type": "generated_by",
        "numeric":   "7",
        "color":     "Shattering the container to reveal what was inside",
    },
    "∑": {
        "key":       "SUM",
        "symbol":    "∑",
        "name":      "Summarize",
        "meaning":   "Autoinjective collapse — map everything to the single core IP",
        "prompt_verb": "SUMMARIZE OPERATOR — autoinjective collapse. One sentence only. No preamble, no explanation, no 'The core is'. Output the single essential information point that contains everything else:",
        "edge_type": "evolved_from",
        "numeric":   "8",
        "color":     "All colors mixed collapse to the one tone that carries everything",
    },
    "S": {
        "key":       "STORE",
        "symbol":    "S",
        "name":      "Store",
        "meaning":   "Store content to field unchanged — no LLM call",
        "prompt_verb": "",
        "edge_type": "generated_by",
        "numeric":   "9",
        "color":     "The canvas preserved exactly as painted",
    },
}

# ---------------------------------------------------------------------------
# DERIVED LOOKUP TABLES  (built once from OPERATOR_TABLE — never written by hand)
# ---------------------------------------------------------------------------

# symbol → edge_type         e.g. "↻" → "evolved_from"
SYMBOL_TO_EDGE = {sym: d["edge_type"] for sym, d in OPERATOR_TABLE.items()}

# symbol → short meaning     e.g. "↻" → "Recursion"
SYMBOL_TO_NAME = {sym: d["name"] for sym, d in OPERATOR_TABLE.items()}

# numeric key → symbol       e.g. "5" → "↻"
NUMERIC_TO_SYMBOL = {d["numeric"]: sym for sym, d in OPERATOR_TABLE.items()}

# symbol → prompt verb       e.g. "^" → "Amplify..."
SYMBOL_TO_PROMPT = {sym: d["prompt_verb"] for sym, d in OPERATOR_TABLE.items()}

# All valid symbols as a set
VALID_SYMBOLS = set(OPERATOR_TABLE.keys())

# ---------------------------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------------------------

def parse_numeric_ops(raw: str) -> list[str]:
    """
    Convert a comma-separated numeric string to a list of operator symbols.
    '1,5,7' → ['+', '↻', '!']
    Repeated digit means repeated operator:  '55' → ['↻', '↻']
    Unknown digit is silently skipped.
    """
    symbols = []
    for token in raw.split(","):
        token = token.strip()
        for ch in token:                      # support '55' → two ↻
            sym = NUMERIC_TO_SYMBOL.get(ch)
            if sym:
                symbols.append(sym)
    return symbols


def build_operator_prompt(op_symbol: str, idea: str, seed: str) -> str:
    """
    Build the LLM prompt for a single operator application.
    All prompt construction is centralised here.
    """
    verb = SYMBOL_TO_PROMPT.get(op_symbol,
           f"Transform this idea (operator {op_symbol}):")
    anchor = f'Stay aligned with the original seed: "{seed}".\nBe specific and sharp.\n\n'
    return f"{anchor}{verb}\n{idea}"


def operator_menu_lines() -> list[str]:
    """Return printable menu lines for operator selection."""
    lines = []
    for sym, d in OPERATOR_TABLE.items():
        lines.append(f"  {d['numeric']} → {sym}  {d['name']:14s}  {d['meaning']}")
    return lines


# ---------------------------------------------------------------------------
# PRESET MODES
# Each mode is (display_name, list_of_operator_symbols).
# ---------------------------------------------------------------------------

MODES = {
    "1": ("🧠 Balanced",    ["↻", "^", "!"]),
    "2": ("💡 Innovator",   ["↻", "^", "!", "!"]),
    "3": ("🔧 Builder",     ["÷", "^", "↻"]),
    "4": ("🔥 Disruptor",   ["!", "↻", "^"]),
    "5": ("🎭 Chaos",       ["!", "!", "!"]),
    "6": ("🧘 Philosopher", ["+", "−", "↻"]),
}


def modes_menu_lines() -> list[str]:
    lines = []
    for k, (name, ops) in MODES.items():
        lines.append(f"  {k}: {name:20s}  {' '.join(ops)}")
    return lines
