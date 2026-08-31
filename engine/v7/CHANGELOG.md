# SToE Information Field — Full Changelog

---

# SToE Information Field — v34 Release Notes

## What's New in v34

### 1. `operators.py` — Single Source of Truth (new file)

**Problem fixed:** Operator logic was floating across three files simultaneously.
`engine_v2.py` defined `NUM_TO_OP`, `OP_MEANING`, `OP_TO_EDGE`, `MODES`, and
operator prompts independently. `field.py` defined its own `OPERATORS` dict.
They partially overlapped and diverged — adding or changing any operator required
editing multiple places and risking inconsistency.

**Fix:** All operator definitions now live exclusively in `operators.py`.
`field.py` and `engine_v2.py` import from it. Nothing is redefined elsewhere.

**What `operators.py` contains:**
- `OPERATOR_TABLE` — one canonical dict per operator with name, meaning, prompt verb,
  edge type, numeric key, and color analogy
- Derived lookups built automatically from the table:
  `SYMBOL_TO_EDGE`, `SYMBOL_TO_NAME`, `NUMERIC_TO_SYMBOL`
- `parse_numeric_ops()` — converts `"5,6,7"` → `['↻', '^', '!']`
- `build_operator_prompt()` — builds the LLM prompt for any operator
- `MODES` — all preset mode definitions
- `operator_menu_lines()`, `modes_menu_lines()` — printable UI menus

Adding a new operator now requires editing **one file in one place**.

---

### 2. `∑` Summarize Operator Added (operator #8)

**Symbol:** `∑`
**Name:** Summarize
**Meaning:** Autoinjective collapse — maps everything to the single core
information point. The field contains itself; this operator forces that collapse.

**Prompt sent to LLM:**
> Apply autoinjective collapse: distill this to the single essential information
> point. One sentence. No preamble. The core IP only.

**Edge type:** `evolved_from`
**Numeric key:** `8`

Use `∑` as the final operator in a chain to crystallize a recursive sequence
into its essential IP. Recommended pattern: `↻ ^ ∑` (evolve → amplify → collapse).

---

### 3. `engine_v2.py` — Clean Operator Wiring

The engine no longer defines any operator data locally. All operator logic
flows through `operators.py`:

- `apply_operator()` calls `build_operator_prompt()` from operators.py
- Edge types are looked up via `SYMBOL_TO_EDGE`
- Operator names for display come from `SYMBOL_TO_NAME`
- Operator selection menu is rendered via `operator_menu_lines()` and `modes_menu_lines()`
- Numeric parsing goes through `parse_numeric_ops()`

**Also simplified:**
- `run_idea_mode()` and `run_question_mode()` extracted as separate functions
- `conserve_failed()` helper centralises Ghost node creation
- Single `OUTPUT_FILE` per session (no duplicate timestamp variable)
- Operator selection UI consolidated into `select_operators()`

---

### 4. `field.py` — Imports Operators from Single Source

`field.py` no longer defines its own `OPERATORS` dict.
It now imports `SYMBOL_TO_EDGE as OPERATORS` from `operators.py`.

---

## Full Operator Table (v34)

| # | Symbol | Name         | Meaning                                          | Edge type        |
|---|--------|--------------|--------------------------------------------------|------------------|
| 1 | `+`    | Connection   | Join two IPs in co-presence; both remain intact  | connected_to     |
| 2 | `−`    | Removal      | Remove weak parts; isolate the core              | removed_from     |
| 3 | `×`    | Synergy      | Create amplified emergent IP from two inputs     | synergy_with     |
| 4 | `÷`    | Distribution | Spread A through the context/shape of B          | distributed_to   |
| 5 | `↻`    | Recursion    | Self-apply iteratively; evolve through cycles    | evolved_from     |
| 6 | `^`    | Amplification| Aggressive resonance escalation                  | amplified_from   |
| 7 | `!`    | Disruption   | Challenge core assumptions; break the frame      | generated_by     |
| 8 | `∑`    | Summarize    | Autoinjective collapse to single core IP         | evolved_from     |

## Preset Modes

| # | Name          | Operators   |
|---|---------------|-------------|
| 1 | 🧠 Balanced   | `↻ ^ !`     |
| 2 | 💡 Innovator  | `↻ ^ ! !`   |
| 3 | 🔧 Builder    | `÷ ^ ↻`     |
| 4 | 🔥 Disruptor  | `! ↻ ^`     |
| 5 | 🎭 Chaos      | `! ! !`     |
| 6 | 🧘 Philosopher| `+ − ↻`     |

## Files

```
stoe_field_34/
├── operators.py          ← NEW: single source of truth for all operator logic
├── engine_v2.py          ← cleaned: imports all operators from operators.py
├── field.py              ← updated: imports OPERATORS from operators.py
├── server.py             ← unchanged
├── start.py              ← version bump to v34
├── static/
│   └── index.html        ← version bump to v34
└── CHANGELOG_v34.md      ← this file
```

## Migration from v33

No breaking changes. Drop in as replacement.
If you have a `field_data.json` from a previous version, copy it into the
`stoe_field_34/` folder before running — all conserved information points
carry forward automatically.

```
copy C:\path\to\stoe_field_33\field_data.json C:\path\to\stoe_field_34\field_data.json
```

---

# SToE Information Field — v35 Release Notes

## What's New in v35

### 1. Operator Editor — Right-Click to Edit, Inline Add

Operators are now fully editable from the UI without touching any code.

**Right-click any operator button** → modal popup opens with:
- **Symbol** — the character shown on the button (editable, max 4 chars)
- **Name** — display name shown in modal title
- **Description** — the tooltip text shown on hover
- **Prompt** — the exact text sent to the LLM when this operator is applied

**Save** persists to `operators_custom.json` on disk. The server reads this
file at every operator call, so changes take effect immediately — no restart needed.

**Delete** button removes the operator from the list and from any active
selection. Confirmation required.

**`+` button** at the end of the operator row opens the same modal with blank
fields to add a brand new operator. Duplicate symbols are rejected.

All operators — including newly added ones — are immediately available for
selection and run through the engine exactly like built-in ones.

---

### 2. Operator Persistence — `operators_custom.json`

New file created on first save: `operators_custom.json` in the project folder.

- Server loads this file at startup and on every `apply_operator` call
- Falls back to `operators.py` defaults if the file is missing or corrupt
- Two new API endpoints:
  - `GET /api/operators` — returns current operator list (custom or default)
  - `POST /api/operators/save` — validates and persists operator list
- `apply_operator` now builds LLM prompts from `operators_custom.json`,
  so editing a prompt in the UI changes what the LLM actually receives

---

### 3. Iterations — Direct Input

The iterations control is redesigned:

- **Renamed** from `iter` label to `Iterations`
- **Direct input** — click the number and type any value directly
- **`+` / `−` buttons** still work as before
- **Validation:**
  - Non-numeric characters are stripped on input
  - Values below 1 are clamped to 1
  - Values above 20 are clamped to 20
  - Empty field on blur resets to 1
- **Max raised** from 10 to 20

---

### 4. Dynamic Operator Button Rendering

Operator buttons are no longer hardcoded in HTML. They are rendered
dynamically from the operator list loaded from the server on startup.

This means:
- Adding an operator in the UI adds a real button to the row instantly
- Deleting an operator removes its button
- Editing a symbol updates the button text
- The selected state (highlight) is preserved across re-renders

---

## Files Changed in v35

```
stoe_field_35/
├── operators_custom.json     ← NEW: created on first operator save
├── server.py                 ← added /api/operators, /api/operators/save,
│                                 apply_operator now uses custom prompts
├── static/index.html         ← operator bar rewritten as dynamic render,
│                                 modal added, iter input redesigned,
│                                 operator management JS added (~120 lines)
├── operators.py              ← unchanged (still the default fallback)
├── field.py                  ← unchanged
├── engine_v2.py              ← unchanged
├── start.py                  ← version bump to v35
└── CHANGELOG_v35.md          ← this file
```

## Migration from v34

No breaking changes. Drop in as replacement.

Copy your field data:
```
copy C:\path\to\stoe_field_34\field_data.json C:\path\to\stoe_field_35\field_data.json
```

If you had no custom operators in v34, `operators_custom.json` will be created
automatically on your first save. Until then the defaults from `operators.py` are used.

---

### 5. Sequence Drag-and-Drop Reordering *(added post v35 release)*

The operator sequence chips are now draggable.

**How it works:**
- Drag any chip left or right to reorder the sequence
- A blue left-border highlight shows the insertion point
- Drop → sequence updates instantly, iterations counter syncs to new length
- The reordered sequence (`manualSeq`) is used for the next run

**Resetting manual order:**
Any of these clears the manual order and returns to auto-build:
- Clicking an operator button to toggle it on/off
- Applying a preset
- Changing iterations via `+` / `−` buttons or direct input

**Iterations sync on operator click:**
Clicking an operator button now immediately updates the Iterations counter
to reflect the new sequence length — no need to adjust it separately.

---

# SToE Information Field — v36 Release Notes

## What's New in v36

### 1. Sequence Drag-and-Drop Reordering

The operator sequence chips are now draggable — reorder the sequence
directly without rebuilding it from scratch.

**How it works:**
- Drag any chip left or right within the sequence
- A blue left-border highlight marks the insertion point as you drag
- Drop → sequence updates instantly, Iterations counter syncs to new length
- The reordered sequence is stored as `manualSeq` and used for the next run

**Resetting manual order** — any of these clears `manualSeq` and returns
to auto-build from selected operators:
- Toggling any operator button on or off
- Applying a preset
- Changing Iterations via `+` / `−` buttons or direct input

---

### 2. Iterations Syncs on Operator Click

Clicking an operator button now immediately updates the Iterations counter
to reflect the new sequence length. No need to adjust it separately after
adding or removing an operator from the selection.

---

## Files Changed in v36

```
stoe_field_36/
├── static/index.html     ← draggable sequence chips, syncIterInput on toggle,
│                            manualSeq state, drag CSS (.dragging, .drag-over)
├── start.py              ← version bump to v36
├── engine_v2.py          ← version bump to v36
├── field.py              ← version bump to v36
├── operators.py          ← version bump to v36
└── CHANGELOG_v36.md      ← this file
```

## Migration from v35

No breaking changes. Drop in as replacement.

```
copy C:\path\to\stoe_field_35\field_data.json C:\path\to\stoe_field_36\field_data.json
copy C:\path\to\stoe_field_35\operators_custom.json C:\path\to\stoe_field_36\operators_custom.json
```

---

# SToE Information Field — v37 Release Notes

## What's New in v37

### 1. Iterations Sync Bug Fix

**Problem:** Selecting 4 operators kept the Iterations counter at 3.

**Root cause:** `syncIterInput()` called `buildSeq()` which used the
stale `iterations` value to build the sequence — making it circular.
If iterations was 3 and you selected 4 operators, `buildSeq` returned
3 items, so `syncIterInput` set iterations back to 3.

**Fix:** `toggleOpBtn` now sets `iterations = selectedOps.length`
directly before any render — no intermediate `buildSeq` call involved.
4 operators selected → Iterations shows 4 immediately.

---

## Files Changed in v37

```
stoe_field_37/
├── static/index.html     ← toggleOpBtn iteration sync fix
├── start.py              ← version bump to v37
├── engine_v2.py          ← version bump to v37
├── field.py              ← version bump to v37
├── operators.py          ← version bump to v37
└── CHANGELOG_v37.md      ← this file
```

## Migration from v36

```
copy C:\path\to\stoe_field_36\field_data.json C:\path\to\stoe_field_37\field_data.json
copy C:\path\to\stoe_field_36\operators_custom.json C:\path\to\stoe_field_37\operators_custom.json
```

---

# SToE Information Field — v38 Release Notes

## What's New in v38

### 1. Operator Buttons Are Now a Palette

Operator buttons no longer toggle on/off. They are a palette —
each click **appends** that operator to the sequence.

This means:
- You can add the same operator multiple times (e.g. ↻ ↻ ^ ↻)
- The sequence is built explicitly, not derived from a set
- No more selected/highlighted state on operator buttons

---

### 2. Remove from Sequence — Right-Click or Drag to Trash

**Right-click** any chip in the sequence → removes it instantly.

**Drag** a chip to the `✕` trash zone at the end of the sequence row →
removes it on drop. The trash zone highlights red when a drag is in progress.

If the sequence becomes empty after a removal, it resets to `[↻]` as a safe fallback.

---

### 3. Default — 1 Iteration, ∑ Summarize

On startup the sequence defaults to `[∑]` — one summarize pass.
This is the most useful single-operator starting point.

---

### 4. Iterations Input Behaviour Updated

- `+` button appends the last operator in the sequence again
- `−` button trims the last chip from the sequence
- Direct input extends (repeating last op) or trims to match the entered number
- All changes reflect immediately in the sequence chips

---

### 5. Presets Set Sequence Directly

Applying a preset now writes directly to `manualSeq` rather than
going through `selectedOps`. The sequence chips update immediately.

---

## Files Changed in v38

```
stoe_field_38/
├── static/index.html     ← palette operator model, contextmenu remove,
│                            drag-to-trash, default ∑, all iter/preset wiring
├── start.py              ← version bump to v38
├── engine_v2.py          ← version bump to v38
├── field.py              ← version bump to v38
├── operators.py          ← version bump to v38
└── CHANGELOG_v38.md      ← this file
```

## Migration from v37

```
copy C:\path\to\stoe_field_37\field_data.json C:\path\to\stoe_field_38\field_data.json
copy C:\path\to\stoe_field_37\operators_custom.json C:\path\to\stoe_field_38\operators_custom.json
```

---

# SToE Information Field — v39 Release Notes

## What's New in v39

### 1. Schema Cleanup

**IPs and Edges now use 16-character UUIDs** (was 8).

**Removed fields from IP:** `known`, `unknown` (content is the known part —
no need to duplicate), `timestamp` (redundant with `created_at`), `alive`
(never changed).

**Removed fields from Edge:** `timestamp` (redundant with `created_at`).

No migration needed — start fresh. Old `field_data.json` files with 8-char
IDs and removed fields continue to load and display; new points written from
v39 onward use the clean schema.

---

### 2. Connections Tab (between Field and Agent)

A dedicated tab for exploring the connection graph. Two sub-views:

**⇔ Connections — Graph**
- Same canvas/zoom/pan/drag as the IP graph
- Edges are the focus: thicker lines (1.5–3px), labeled with type and note
  at the curve midpoint, with directional arrows
- Nodes are small and dim — supporting cast, not the star
- Click an edge → highlights it + shows an info panel at the bottom of the
  canvas with Edge ID, Source ID, Target ID, Type, Note
- Click empty space → deselects

**≡ Conn Table**
- Columns: Edge ID, Source ID, Source content (preview), Target ID,
  Target content (preview), Type, Weight, Note, Created, Actions
- Filter by any field
- Edit (✎) and Delete (✕) buttons per row

---

### 3. Add / Edit / Delete IPs

**＋ Add IP button** in the field view toolbar.

**Right-click any node** in the graph → context menu:
- ✎ Edit IP — opens modal with Content, Category, Type fields
- ⇔ Connect from here — opens connection modal with source pre-filled
- 📄 Load file as IP — loads a .txt/.md/.pdf as a single IP (no chunking)
- ✕ Delete IP — deletes IP and all its edges (with confirmation)

**Right-click empty canvas** → Add IP option.

**Edit (✎) and Delete (✕) buttons** in the IP table rows.

IP Modal fields: Content (textarea), Category (dropdown), Type (imaginary/physical).

---

### 4. Add / Edit / Delete Connections

**⇔ Add Conn button** in the field view toolbar.

Connection Modal fields:
- Source ID (16-char)
- Target ID (16-char)
- Type (dropdown of all 12 SToE edge types)
- Weight (0–1)
- Note / Description

Edit and Delete available from the Connections table and the connection modal.

---

### 5. File-to-Single-IP

Right-click a node → "📄 Load file as IP" → pick .txt, .md, or .pdf.
The entire file is loaded as one IP with no chunking. Content is pre-filled
in the IP modal for review before saving.

---

### 6. Four-Tab Field View

Tabs: **⬡ Graph** | **☰ Table** | **⇔ Connections** | **≡ Conn Table**

Graph and Table tabs now show IPs. Connections and Conn Table show edges.

---

## New Server Endpoints in v39

| Method | Path | Description |
|--------|------|-------------|
| PUT | `/api/points/<id>` | Edit content, category, type of an IP |
| DELETE | `/api/points/<id>` | Hard delete IP and its edges |
| GET | `/api/connections` | All edges with source/target content previews |
| PUT | `/api/connections/<id>` | Edit edge type, note, weight |
| DELETE | `/api/connections/<id>` | Hard delete an edge |

---

## Files Changed in v39

```
stoe_field_39/
├── field.py          ← 16-char UUIDs, removed known/unknown/timestamp/alive
├── server.py         ← 5 new endpoints
├── static/index.html ← 4-tab field view, connections graph, connections table,
│                         IP modal, connection modal, context menu,
│                         file-to-single-IP, table action buttons
├── start.py          ← version bump
├── engine_v2.py      ← version bump
├── operators.py      ← version bump
└── CHANGELOG_v39.md  ← this file
```

## Migration from v38

No field data migration needed — start fresh or carry existing `field_data.json`.

```
copy C:\path\to\stoe_field_38\operators_custom.json C:\path\to\stoe_field_39\operators_custom.json
```

---

# SToE Information Field — v40 Release Notes

## What's New in v40

### 1. Single Version Variable

**`version.py`** — new file, one line to change for any future bump:
```python
VERSION = "v40"
```

All Python files import from it:
- `start.py` — banner
- `engine_v2.py` — header comment + startup print
- `field.py` — header comment
- `operators.py` — header comment
- `server.py` — header comment + exposed in `/api/meta` response as `"version"`

**`index.html`** — single JS constant at the top of the script block:
```javascript
const VERSION = 'v40';  // ← single place to update version in JS
```
Injected into the logo badge (`<sub id="version-badge">`) and `<title>` on
`DOMContentLoaded`. No more scattered hardcoded strings in HTML.

To bump to v41: change `VERSION = "v40"` in `version.py` and
`const VERSION = 'v40'` in `index.html`. That's it.

---

### 2. Bug Fixes from v39 Testing

**Operator buttons not rendering** — added `DEFAULT_OPERATORS` hardcoded
in JS. If `/api/operators` is slow or returns empty, all 8 buttons render
immediately from the JS constant. No blank palette on load.

**Connections tab missing** — was nested inside Field View instead of being
a proper top-level tab. Moved to the main tab bar between Field View and Agent.
Has its own Graph / ≡ Table sub-tabs and Add Conn button.

**Sequence ∑ chip missing on load** — `manualSeq = ['∑']` is now set before
`renderOpButtons()` in the init flow, ensuring the default chip always appears.

**`setFieldView` / `setConnView` split** — Field View now only handles Graph
and Table sub-tabs. Connections view has its own `setConnView('graph'|'table')`
function. No cross-contamination.

---

## To Update Version in Future

1. `version.py` → change `VERSION = "vXX"`
2. `static/index.html` → change `const VERSION = 'vXX'`
3. Create `CHANGELOG_vXX.md`

---

## Files Changed in v40

```
stoe_field_40/
├── version.py            ← NEW: single version source for Python
├── server.py             ← imports VERSION, exposes in /api/meta
├── engine_v2.py          ← imports VERSION
├── field.py              ← imports VERSION
├── operators.py          ← imports VERSION
├── start.py              ← imports VERSION
├── static/index.html     ← const VERSION, dynamic badge/title,
│                            DEFAULT_OPERATORS fallback,
│                            Connections as top-level tab,
│                            setConnView(), bug fixes
└── CHANGELOG_v40.md      ← this file
```

## Migration from v39

```
copy C:\path\to\stoe_field_39\field_data.json C:\path\to\stoe_field_40\field_data.json
copy C:\path\to\stoe_field_39\operators_custom.json C:\path\to\stoe_field_40\operators_custom.json
```

---

# SToE Information Field — v41 Release Notes

## What's New in v41

### Version in `.env` — Single Place to Change

`version.py` is removed. Version now lives in `.env`:

```
VERSION=v41
```

**Python files** read it via `os.getenv("VERSION", "v41")` after `load_dotenv`.
Covers: `server.py`, `engine_v2.py`, `field.py`, `operators.py`, `start.py`.

**Server** exposes it in `/api/meta` response as `"version"`.

**`index.html`** fetches it from `/api/meta` on startup and injects it into
the logo badge and page title. Fallback `'v41'` is used until server responds.

To bump to v42: change `VERSION=v41` to `VERSION=v42` in `.env`. Done.

---

## Files Changed in v41

```
stoe_field_41/
├── .env                  ← VERSION=v41 added
├── version.py            ← REMOVED
├── server.py             ← VERSION = os.getenv("VERSION")
├── engine_v2.py          ← VERSION = os.getenv("VERSION")
├── field.py              ← VERSION = os.getenv("VERSION")
├── operators.py          ← VERSION = os.getenv("VERSION")
├── start.py              ← VERSION = os.getenv("VERSION")
├── static/index.html     ← loadVersion() fetches from /api/meta
└── CHANGELOG_v41.md      ← this file
```

## Migration from v40

```
copy C:\path\to\stoe_field_40\field_data.json C:\path\to\stoe_field_41\field_data.json
copy C:\path\to\stoe_field_40\operators_custom.json C:\path\to\stoe_field_41\operators_custom.json
```

---

# SToE Information Field — v42 Release Notes

## What's New in v42

### Bug Fixes from v41 Testing

**`{VERSION}` literal in terminal banner** — `print("""...""")` was not an
f-string so `{VERSION}` printed literally. Fixed to `print(f"""...""")`.

**`await` crashing entire JS script** — the `.then(() => { ... })` callback
in `window.load` was not declared `async`, causing a syntax error at the
first `await` call. This killed the entire script block — `switchTab`,
`setMode`, and every function defined below line 711 became undefined,
producing a cascade of `ReferenceError` on every click. Fixed to
`.then(async () => { ... })`.

---

## Files Changed in v42

```
stoe_field_42/
├── .env                  ← VERSION=v42
├── start.py              ← f-string banner fix
├── static/index.html     ← async .then() callback fix, version bump
├── server.py             ← version bump (fallback)
├── engine_v2.py          ← version bump (fallback)
├── field.py              ← version bump (fallback)
├── operators.py          ← version bump (fallback)
└── CHANGELOG_v42.md      ← this file
```

## Migration from v41

```
copy C:\path\to\stoe_field_41\field_data.json C:\path\to\stoe_field_42\field_data.json
copy C:\path\to\stoe_field_41\operators_custom.json C:\path\to\stoe_field_42\operators_custom.json
```

---

# SToE Information Field — v43 Release Notes

## What's New in v43

### Bug Fix — JS Syntax Error in PDF-to-IP Handler

A literal newline character was embedded inside a single-quoted JS string
in the `onFileToIP` function:

```js
// broken
text += tc.items.map(it=>it.str).join(' ') + '
';

// fixed
text += tc.items.map(it=>it.str).join(' ') + '\n';
```

This caused `Uncaught SyntaxError: Invalid or unexpected token` at line 2193,
which killed everything defined after it — including `setMode`, `switchTab`,
and all operator/sequence logic. Fixed to use the `'\n'` escape sequence.

---

## Files Changed in v43

```
stoe_field_43/
├── .env                  ← VERSION=v43
├── static/index.html     ← literal newline fix in onFileToIP
└── CHANGELOG_v43.md      ← this file
```

## Migration from v42

```
copy C:\path\to\stoe_field_42\field_data.json C:\path\to\stoe_field_43\field_data.json
copy C:\path\to\stoe_field_42\operators_custom.json C:\path\to\stoe_field_43\operators_custom.json
```

---

# SToE Information Field — v44 Release Notes

## What's New in v44

### Single IP File Loading

New **Single IP** option added to the Chunk by radio group in File mode
(highlighted in cyan to distinguish it from chunking modes).

**Behaviour:**
- Select a file, choose Single IP, click Run
- Entire file text is loaded into the IP modal (up to 8000 chars)
- Review and edit content, category, type before saving
- No chunking, no engine run — direct field insertion

**Tooltip:** `Entire file as one IP — opens in IP modal`

Works with .txt, .md, .pdf, .csv. For PDF, text is extracted via PDF.js
before loading into the modal.

---

## Files Changed in v44

```
stoe_field_44/
├── .env                  ← VERSION=v44
├── static/index.html     ← Single IP radio, preview desc, pipeline intercept
└── CHANGELOG_v44.md      ← this file
```

## Migration from v43

```
copy C:\path\to\stoe_field_43\field_data.json C:\path\to\stoe_field_44\field_data.json
copy C:\path\to\stoe_field_43\operators_custom.json C:\path\to\stoe_field_44\operators_custom.json
```


---

### Passthrough Operator + 50,000 Char Limit (added to v44)

**Char limit bumped** from 8,000 to 50,000 for Single IP and file-to-IP loading.

**Passthrough operator** — create an operator with an empty prompt field.
When that operator is used in Single IP mode, the file is stored directly
to the field without any LLM call:

| Column | Value |
|---|---|
| `content` | full file text (up to 50,000 chars) |
| `category` | Seed |
| `type` | physical |
| `operator` | the operator symbol |
| `score` | `{}` — no LLM scoring |
| `metadata` | `{ source: filename, passthrough: true, char_count: N }` |

If multiple files are selected in Single IP mode, each is stored as a
separate IP. If the operator has a non-empty prompt, files open in the
IP modal for review as before.

---

# SToE Information Field — v45 Release Notes

## What's New in v45

Version bump from v44. All v44 features carry over:

- Single IP file loading mode
- Passthrough operator (empty prompt = store directly, no LLM)
- 50,000 char limit for file-to-IP
- Full 4-tab field view (Graph, Table, Connections, Conn Table)
- Operator editor (right-click to edit, + to add)
- Sequence drag-and-drop reordering
- IP and Connection CRUD with modals and context menu
- Version sourced from `.env`

---

## Migration from v44

```
copy C:\path\to\stoe_field_44\field_data.json C:\path\to\stoe_field_45\field_data.json
copy C:\path\to\stoe_field_44\operators_custom.json C:\path\to\stoe_field_45\operators_custom.json
```

---

# SToE Information Field — v46 Release Notes

## What's New in v46

### Store (S) Operator Added to Defaults

`S` passthrough operator is now included in the default operator set —
no need to create it manually.

| Field | Value |
|---|---|
| Symbol | `S` |
| Name | Store |
| Description | Store content to field unchanged — no LLM call |
| Prompt | *(empty — triggers passthrough)* |
| Numeric key | `9` |
| Edge type | `generated_by` |

Available in `operators.py`, `DEFAULT_OPERATORS` in JS, and served via
`/api/operators` on startup.

---

## Files Changed in v46

```
stoe_field_46/
├── .env                  ← VERSION=v46
├── operators.py          ← S Store operator added
├── static/index.html     ← S Store in DEFAULT_OPERATORS, version bump
└── CHANGELOG_v46.md      ← this file
```

## Migration from v45

```
copy C:\path\to\stoe_field_45\field_data.json C:\path\to\stoe_field_46\field_data.json
copy C:\path\to\stoe_field_45\operators_custom.json C:\path\to\stoe_field_46\operators_custom.json
```

Note: if you have an `operators_custom.json` from v45, the `S` operator
may not appear until you delete `operators_custom.json` and let the server
regenerate from defaults, or add it manually via the operator editor.

---

# SToE Information Field — v47 Release Notes

## What's New in v47

### Bug Fix — HTTP 500 on Field Load

`timestamp` removed in v39 schema still referenced in sort/search. Fixed
to use `created_at` ISO string with `timestamp` as legacy fallback.

### Connections Graph — Shows All IPs

All IPs now render as nodes even with 0 edges.

### IP Selection on Connections Graph

Click nodes to toggle into Generate selection (highlighted + glowing).

### ⚡ Generate Connections Panel (new sub-tab)

**IP Selection:** click graph nodes, type IDs, or click ⊕ in IP Table.
**Operators:** toggleable palette, defaults to `+ × − ↻ ^`.
**Custom prompt:** overrides operator prompt if filled.
**N per pair:** how many edges per IP pair per operator.
**Generate:** LLM produces one-sentence relationship per pair×op×N,
stored as typed edge. Auto-switches to graph when done.

**⊕ button** added to IP Table rows — adds IP to Generate selection.

## Migration from v46

```
copy C:\path\to\stoe_field_46\field_data.json C:\path\to\stoe_field_47\field_data.json
copy C:\path\to\stoe_field_46\operators_custom.json C:\path\to\stoe_field_47\operators_custom.json
```

---

# SToE Information Field — v48 Release Notes

## What's New in v48

### Selection Limited to 2 IPs

Generate Connections now enforces a maximum of 2 IPs:
- Clicking a third node on the graph shows a notify and does nothing
- Typing a third ID into the manual input shows a notify and does nothing
- Clear one first before adding another

### IP Table ⊕ Button Removed

Table-based IP selection for Generate removed for now.
Use the graph (click nodes) or manual ID input instead.

---

## Files Changed in v48

```
stoe_field_48/
├── .env              ← VERSION=v48
├── static/index.html ← 2-IP selection limit, ⊕ button removed
└── CHANGELOG_v48.md
```

## Migration from v47

```
copy C:\path\to\stoe_field_47\field_data.json C:\path\to\stoe_field_48\field_data.json
copy C:\path\to\stoe_field_47\operators_custom.json C:\path\to\stoe_field_48\operators_custom.json
```

---

# SToE Information Field — v49 Release Notes

## What's New in v49

### Bug Fix — Load Field Button Broken

`SyntaxError: Invalid or unexpected token` at line 2504 — literal newline
characters inside single-quoted JS strings in the `generateConnections`
prompt builder:

```js
// broken
prompt = customPrompt + '
\nIP A: ' + ...

// fixed
prompt = customPrompt + '\n\nIP A: ' + ...
```

Same cascade pattern as before — parser dies, everything below including
`loadFieldJson` becomes undefined.

---

## Files Changed in v49

```
stoe_field_49/
├── .env              ← VERSION=v49
├── static/index.html ← literal newline fix in generateConnections
└── CHANGELOG_v49.md
```

## Migration from v48

```
copy C:\path\to\stoe_field_48\field_data.json C:\path\to\stoe_field_49\field_data.json
copy C:\path\to\stoe_field_48\operators_custom.json C:\path\to\stoe_field_49\operators_custom.json
```

---

# SToE Information Field — v50 Release Notes

## What's New in v50

### Node Selection Fix

Click-to-select now uses a drag threshold — a short click selects the node,
moving the mouse >5px before releasing drags it instead. Previously the first
click always went to drag mode, making selection impossible without shift.

### Add Conn Button Always Opens

Add Conn button now always opens the connection modal regardless of whether
any IPs are selected. If IPs are selected on the graph, source and target
fields are pre-filled. If nothing is selected, fields are empty for manual
entry.

---

## Files Changed in v50

```
stoe_field_50/
├── .env              ← VERSION=v50
├── static/index.html ← click-select threshold, Add Conn always opens
└── CHANGELOG_v50.md
```

## Migration from v49

```
copy C:\path\to\stoe_field_49\field_data.json C:\path\to\stoe_field_50\field_data.json
copy C:\path\to\stoe_field_49\operators_custom.json C:\path\to\stoe_field_50\operators_custom.json
```

---

# SToE Information Field — v51 Release Notes

## What's New in v51

Version bump from v50. All v50 fixes carry over:
- Canvas sizing fix for connections graph
- Click-to-select with drag threshold
- Console logs for connection click/mousedown diagnosis
- Add Conn always opens, prefills from selection if available

## Migration from v50

```
copy C:\path\to\stoe_field_50\field_data.json C:\path\to\stoe_field_51\field_data.json
copy C:\path\to\stoe_field_50\operators_custom.json C:\path\to\stoe_field_51\operators_custom.json
```

---

# SToE Information Field — v52 Release Notes

## What's New in v52

### Node Selection Fix — mouseup instead of click

The `click` event was not firing on canvas after `mousedown` — likely
swallowed by the browser's drag detection. Switched selection logic from
`click` to `mouseup`. Node is selected if mouseup fires on same node as
mousedown with <5px movement.

### Add Conn Modal Log

Added `console.log` to `openConnModal` to diagnose why button wasn't
opening the modal.

## Migration from v51

```
copy C:\path\to\stoe_field_51\field_data.json C:\path\to\stoe_field_52\field_data.json
copy C:\path\to\stoe_field_51\operators_custom.json C:\path\to\stoe_field_52\operators_custom.json
```

---

# SToE Information Field — v53 Release Notes

## What's New in v53

### Add Conn Modal Fixed

IP modal and Connection modal were inside the `field-view` div. When the
Connections tab is active, `field-view` has `display:none` — which prevents
`position:fixed` children from rendering even though fixed elements should
escape the normal flow. Both modals moved to body level, outside all tab
containers. Now work from any tab.

## Migration from v52

```
copy C:\path\to\stoe_field_52\field_data.json C:\path\to\stoe_field_53\field_data.json
copy C:\path\to\stoe_field_52\operators_custom.json C:\path\to\stoe_field_53\operators_custom.json
```

---

# SToE Information Field — v54 Release Notes

## What's New in v54

### Connection Modal — Operator Palette + LLM Generation

**Operator buttons** shown in the connection modal. Click any operator to:
- Call LLM with both IP contents + operator name/description
- Fill the Note/Description textarea with a detailed (2-3 sentence) result
- Auto-set the Type dropdown to match the operator's edge type

**✦ Custom Generate button** — generates a rich connection description
without any operator framing. Sends both IP full contents to LLM with
instructions to write at least 3-4 detailed sentences about their relationship.

**Note field** changed from single-line input to resizable textarea.

Store (S) operator is excluded from the palette (no prompt = passthrough).

## Migration from v53

```
copy C:\path\to\stoe_field_53\field_data.json C:\path\to\stoe_field_54\field_data.json
copy C:\path\to\stoe_field_53\operators_custom.json C:\path\to\stoe_field_54\operators_custom.json
```

---

# SToE Information Field — v55 Release Notes

## What's New in v55

### Bug Fix — Literal Newlines in JS Strings

Same recurring issue — literal newline characters inside single-quoted JS
strings in the two new generate functions (`connModalGenerateFromOp` and
`connModalGenerateCustom`). Fixed all occurrences to use `\n` escape sequences.

## Migration from v54

```
copy C:\path\to\stoe_field_54\field_data.json C:\path\to\stoe_field_55\field_data.json
copy C:\path\to\stoe_field_54\operators_custom.json C:\path\to\stoe_field_55\operators_custom.json
```

---

# SToE Information Field — v56 Release Notes

## What's New in v56

### Seed SToE Button — Rich Field from stoe_seed.json

Seed SToE now loads from `stoe_seed.json` instead of generating minimal
hardcoded IPs inline. The seed contains 26 IPs and 31 connections covering
the full SToE ontology.

**IPs included:**
- Core ontology: Everything, Nothing, Observer, Creator
- Three Laws: Conservation, Connection, Autoinjection
- Mathematical: Autoinjection mapping, Information Function, IP concept
- Entities: God, Human, AI, Mykola Voronin
- Framework: SToE, Information Field
- Operators: + × − ↻ ^ ∑ with full descriptions
- Applications: Schrödinger's Cat, Testable Prediction, Architectural Gap, Persistent Reasoning Graph

**Duplicate protection:**
- Checks existing field by content fingerprint before adding
- Skips any IP already present (case-insensitive content match)
- Skips edges where source+target+type already exists
- Reports: added N IPs, M connections (K already existed)
- Clicking Seed SToE on an already-seeded field shows "already seeded" message without modifying anything

## Migration from v55

No field data migration needed — start fresh with Seed SToE.
```
copy C:\path\to\stoe_field_55\operators_custom.json C:\path\to\stoe_field_56\operators_custom.json
```

---

# SToE Information Field — v57 Release Notes

## What's New in v57

### Bug Fix — OLLAMA_URL NameError on Startup

When the seed endpoint was rewritten in v56, the block that defined
`OLLAMA_URL` and `OLLAMA_MODEL` from environment variables was accidentally
removed. Server crashed immediately on start with `NameError: name 'OLLAMA_URL'
is not defined`. Fixed by re-adding both definitions after `VERSION`.

## Migration from v56

```
copy C:\path\to\stoe_field_56\operators_custom.json C:\path\to\stoe_field_57\operators_custom.json
```

---

# SToE Information Field — v58 Release Notes

## What's New in v58

### Bug Fix — _get_models and _call_llm Missing

The seed endpoint replacement in v56 accidentally cut the `_call_llm` and
`_get_models` helper functions. Server crashed with `NameError: name
'_get_models' is not defined`. Both functions restored.

## Migration from v57

```
copy C:\path\to\stoe_field_57\operators_custom.json C:\path\to\stoe_field_58\operators_custom.json
```

---

# SToE Information Field — v59 Release Notes

## What's New in v59

### Bug Fix — Agent `_req` Not Defined

`import requests as _req` was scoped inside `_call_llm` and `_get_models`
functions but the agent chat endpoint used `_req` at module level. Moved
`import requests as _req` to the top of `server.py` so it's globally available.

## Migration from v58

```
copy C:\path\to\stoe_field_58\field_data.json C:\path\to\stoe_field_59\field_data.json
copy C:\path\to\stoe_field_58\operators_custom.json C:\path\to\stoe_field_59\operators_custom.json
```

---


# v60

## Changelog Consolidated

All individual `CHANGELOG_vXX.md` files merged into a single `CHANGELOG.md`.
From v60 onward, new entries are appended here as sections — no more separate
files per version cluttering the root.

---


# v61

## Unified Selection — IP and Edge across all views

**Field View Table**
- Left-click row → selects IP; highlights row (purple), syncs to field graph, shows detail in right panel
- Right-click row → deselects

**Field View Graph**
- Existing click-to-select preserved
- Right-click empty canvas → deselects current IP

**Connections Graph**
- Click node → selects IP, shows detail in right panel
- Click edge → selects edge, shows edge detail in right panel
- Click empty → deselects edge

**Connections Table**
- Left-click row → selects edge (green highlight), syncs to connections graph, shows edge detail in right panel
- Right-click row → deselects
- Switching to Connections Graph tab after selecting in table shows that edge highlighted

**Right Panel**
- IP selected → shows content, category, connections, ✎ Edit and ✕ Delete buttons
- Edge selected → shows Edge ID, Type, Weight, Source, Target, Note, ✎ Edit and ✕ Delete buttons

---


# v62

## Selection Bug Fixes

**IP Table** — highlight was being overwritten by `onmouseout` before the async fetch completed. Fixed by setting row highlight immediately on click before the fetch, independently of re-render.

**Connections Table** — same fix applied. `highlightEdgeRows()` called synchronously on click.

**Connections Graph — node click** — clicking a node no longer shows IP detail in right panel. Nodes are drag-only in the connections graph. Only edge clicks show detail.

**Connections Graph — edge highlight** — when an edge is selected, its two endpoint nodes now glow green (matching the edge color) and grow slightly larger, making the connected IPs clearly visible.

---


# v63

## Multi-select Tables + Conn Graph Edge Selection

**IP Table (Field View)**
- Left-click toggles row selection — rows stay selected until clicked again
- Multiple rows can be selected simultaneously (purple highlight)
- Right-click deselects that row
- Last clicked row's IP shows in right panel

**Connections Table**
- Same toggle behaviour with green highlight
- Multiple edges can be selected simultaneously
- Right-click deselects

**Connections Graph**
- Edges now checked BEFORE nodes in mousedown — prevents nodes near edge midpoints from stealing the click
- Hit test samples 9 points along the quadratic bezier curve (radius 12px each) instead of just the midpoint — much easier to click edges
- Edge click: selects edge, shows detail in right panel, glows both endpoint nodes green
- Node click: drag only — no selection, no detail panel
- Click empty canvas: deselects edge

---


# v64

## Selection Overhaul — Click not Grab, Persist, Multi-highlight

**Field Graph**
- Selection moved from mousedown to mouseup — no more accidental selection while dragging
- Click same node again = deselect (toggle). Click new node = select it
- Click empty canvas = keep current selection (no deselect)
- All `selectedIPIds` from table now highlight in graph (dim others), not just the last clicked

**Connections Graph**
- Edge selection moved from mousedown to mouseup — no more selecting on grab
- Click same edge again = deselect (toggle). Click new edge = select it
- Click node = drag only, no edge deselect
- Click empty canvas = keep selection
- All `selectedEdgeIds` from table now highlight in graph + glow their endpoint nodes

**Table → Graph sync**
- All rows selected in IP Table stay highlighted when switching to Field Graph
- All rows selected in Connections Table stay highlighted when switching to Connections Graph
- Switching tabs no longer loses multi-selection

---


# v65

## Interaction Logger

New `⬇ Log` and `✕ log` buttons in the top toolbar.

`⬇ Log` downloads a `.txt` file with every interaction since page load (or since last clear), formatted as:

```
[1.23s] FIELD_GRAPH | node_select | id="abc123" content="Everything (E)..." category="Star"
[2.45s] IP_TABLE | row_select | id="abc123" selected_count=1
[3.10s] NAV | tab_switch | tab="connections"
[4.20s] CONN_GRAPH | edge_select | id="def456" type="connected_to" src="abc" tgt="xyz"
```

Categories logged: `FIELD_GRAPH`, `IP_TABLE`, `CONN_TABLE`, `CONN_GRAPH`, `NAV`, `GENERATE`, `LOGGER`

Actions logged: node select/deselect, drag, row select/deselect (left and right click), edge select/deselect, gen node select, tab switches, view switches, generate start.

Max 500 entries (oldest dropped). Upload the `.txt` to Claude to explain interaction bugs without screenshots.

---


# v66

## Bug Fix — ⬇ Log Button Downloads Interaction Log

Old `downloadLog()` function (downloading server/session log) was defined after the new interaction logger, overwriting it. Renamed old function to `downloadServerLog()` — still accessible via the session log panel button (now labelled "⬇ server log"). The toolbar **⬇ Log** button now correctly downloads the JS interaction log.

---


# v67

## Fix — Graph Clicks Now Accumulate Selection

**Field graph node clicks** now add to `selectedIPIds` (not replace). Clicking
a selected node removes it from the set. All selected nodes stay dimmed/bright
when switching between Table and Graph. `selectedIP` still tracks the last
clicked node for the detail panel — but the graph highlights ALL `selectedIPIds`.

Log will now show `total=N` on each `node_select` event.

---


# v68

## Graph→Table Sync + Conn Graph Multi-select

**Graph→Table sync** — `isSelRow` was checking `selectedIP` (single) instead of
`selectedIPIds` (Set). Fixed. Table rows now highlight correctly when switching
from graph where multiple nodes were selected.

**renderTable/renderConnTable** — `highlightIPRows()` / `highlightEdgeRows()`
now called via `setTimeout` after innerHTML rebuild, so rows reflect current
Set state on every render.

**Conn graph multi-select** — clicking edges now accumulates into
`selectedEdgeIds` instead of replacing. Click same edge again to deselect it.
Log will show `total=N` on each `edge_select`.

---


# v69

## Deselect All + Conn Graph Pair Selection

**Deselect All buttons:**
- Field View toolbar: **✕ sel** — clears all `selectedIPIds`, resets graph and table highlights
- Connections toolbar: **✕ sel** — clears all `selectedEdgeIds`; **✕ pair** — clears the 2-IP pair for generation

**Conn graph node clicks — IP pair selection:**
- Click a node = add to pair (cyan glow, larger radius)
- Click same node again = remove from pair
- Pair full (2 nodes) = notify + show **⚡ Connect Pair** button in toolbar
- Clicking more than 2 = notify to clear first
- Pair persists when switching between Graph / Table / Generate tabs
- Pair status shown in toolbar: "1 of 2 selected" → "Pair ready"

**⚡ Connect Pair button** — appears in toolbar when pair is complete. Opens
Add Connection modal with Source and Target pre-filled from the pair. Multiple
different connections between the same pair are supported (different types,
operators, notes).

**Visual distinction:**
- Pair nodes: cyan (#22d3ee) glow and stroke, radius 12
- Edge endpoints: green (#4ade80) glow, radius 11
- Generate-selected (both): cyan takes priority

---


# v70

## Table Sorting Fixes

**IP Table** — first click on any column now sorts ascending (↑) not descending.
Default sort is `created_at` ascending. Clicking same column again toggles direction.

**Connections Table** — sorting added. Sortable columns:
Edge ID, Source ID, Target ID, Type, Weight, Created.
Click header to sort ascending, click again to reverse. Sort indicator (↑/↓) shown in header.
Note and Source/Target content columns are not sortable (too variable).

---


# v71

## Stable Table Sort

Both IP table and Connections table now use `id` as a secondary tiebreaker
when primary sort values are equal (e.g. all rows have the same `created_at`).
Sort order no longer flips on repeated clicks when timestamps are identical.

---


# v72

## Newest First by Default + Stable Sort on IP Table

Both IP table and Connections table now default to `created_at` **descending**
— newest items appear at the top. Stable `id` tiebreaker applied to IP table
as well (was only in conn table in v71).

---


# v73

## Export Field Button

New **⬇ Export Field** button in the top toolbar (left of Load Field).
Downloads the current in-memory field as `field_data_2026-05-09T14-35-22.json`
to the browser's Downloads folder. No server call — exports directly from JS.

---


# v74

## Connection Count Fix — Always Accurate

`connections` column was always 0 because counts were only incremented
incrementally on `connect()` calls, never recalculated from the edges array.

**Fixes:**
- `field.py` — new `recalc_connections()` method rebuilds counts from edges
- Called automatically on every `_load()` (startup, Load Field, merge)
- Called after Seed SToE and after IP delete
- New `POST /api/recalc` endpoint for manual trigger
- Existing `field_data.json` will show correct counts immediately on next start

---


# v75

## stoe_seed.json — No Disconnected Nodes

Three operator IPs had 0 connections: `+` (Connection), `−` (Removal), `^` (Amplification).
Several others had only 1. Added 14 semantically meaningful edges:

- `+` → SToE (connected_to), Everything (synergy_with)
- `−` → × Synergy (connected_to), Autoinjection (evolved_from)
- `^` → ↻ Recursion (synergy_with), Architectural Gap (evaluates)
- `∑` → SToE (generated_by)
- `↻` → AI (evaluates)
- `×` → Human (synergy_with)
- Information Field → SToE (connected_to)
- IP → Information Field (connected_to)
- Information Function → IP (generated_by)
- Nothing → Everything (connected_to)
- Testable Prediction → AI (evaluates)

Result: 26 nodes, 45 edges, minimum 2 connections per node.
Wipe field and re-seed to get the updated graph.

---


# v76

## Conn Graph — Node/Edge Click Priority Fix

**Node-first hit detection** — nodes are now checked before edges in mousedown.
Previously edges were checked first (to fix edge clickability), but this caused
nodes sitting on edge paths to fire `edge_select` instead of `pair_node_select`.

**Edge exclusion zone near nodes** — `connHitEdge` now skips bezier sample points
within 18px of any node, so edges near node centers never steal node clicks.
Edges are still easily clickable anywhere along their path away from nodes.

**Result:** clicking a node always selects it as a pair member; clicking an edge
away from nodes selects the edge. No more accidental edge selection when trying
to pick a second pair node.

---


# v77

## Expression-Compressed Seed

stoe_seed.json rebuilt with expressions. Changes:

**Structure:** each node now has three layers:
- `content` — short name/label
- `metadata.expr` — operator expression (formal compression)
- edge `note` — one-sentence semantic connection

**New IPs (4):**
- Human=God theorem: `H×G→∅; H=G|creative_capacity`
- Fear-Evolution duality: `(H×AI)-(Fear^↻)=(H×AI)^exp(evolution)`
- Lemniscate identity: `∑(all IP)=E=1IP, |Field|=∞=1`
- SToE self-reference: `SToE∈Field(SToE), navigator∈Field(navigator)`

**Result:** 30 nodes, 58 edges, no disconnected nodes, avg 3.9 connections.

Wipe field and Seed SToE to load new seed.

---


# v78

Version bump. No functional changes from v77.

---


# v79

## Right Panel Font Size Increase

All text in the IP and edge detail panels increased for readability:
- IP content: 13px → 16px
- Edge content text: 11px → 14px
- Labels: 10px → 12px
- IDs: 9px → 12px
- Adjacency edge type: 8px → 11px
- Adjacency content: implicit → 13px
- IP metadata line: 9px → 12px

---


# v80

## G=E Theorem Added to Seed

New node: **God=Everything theorem**
- `expr: G=E: God∈Everything, Everything∈God, G↔E autoinjective`
- Connected to: God (evaluates), Everything (evaluates), Autoinjection (evolved_from), SToE (connected_to)

Also fixed the incorrect `God generated_by Everything` edge — replaced with bidirectional `synergy_with` edges reflecting that G and E are the same point observed from different positions, neither generating the other.

Seed now: 31 nodes, 63 edges.

---


# v81

## New IP Schema — Name + Description + Expression

IP schema now has three distinct fields alongside content:
- `name` — short label (e.g. "God (G)", "Law of Conservation")
- `expression` — operator notation (e.g. "G=E: God∈Everything")
- `description` — prose explanation
- `content` — full text kept for search and LLM context

**Migration:** `migrate_schema()` runs on every load — existing nodes get name extracted from content (text before " — "), expression from `metadata.expr`, description from `metadata.description`. No data loss.

**UI changes:**
- IP Table: Name, Description, Expression columns (expression in cyan)
- IP Modal: four separate fields
- IP Detail panel: name large at top, expression in cyan below, description in muted text
- Graph nodes continue to use name for labels

**Seed:** all 31 nodes migrated to new schema.

---


# v82

## Final seed — 36 nodes, 113 edges

stoe_seed.json updated with Mykola Voronin's own naming and structure:
- 5 paper nodes with distinct names (SToE 2021: Algorithms Ideas & AI, Autoinjection: 4th Mapping Class, SToE as Cognitive Architecture, AI Architectural Gap Derivation, SToE: Three Foundational Laws)
- 36 nodes total, 113 edges, avg 6.3 connections, no disconnected nodes
- New IP schema: name + expression + description + content

---


# v7

Fresh track branched from v82. Imports the two highest-value insights from
the `stoe_v3` experimental harness into the navigator: topology-aware
context retrieval and prompt observability.

## 1. Topology-aware context for every LLM call

Before v7, operator and connection-generation prompts received only the
focal IPs' own content. The depth-1 neighborhoods — including any
`failed_from` or `contradicts` edges — were invisible to the model. This
is exactly the gap `stoe_v3`'s `TopologyContext.build()` was designed to close.

In v7, every LLM-bound endpoint walks the graph from the focal IPs and
surfaces depth-1 neighbors as part of the prompt, with explicit edge-type
tags and an instruction to avoid re-attempting recorded dead-ends.

**Backend** — `server.py`:
- New `_topology_context(node_ids, max_per_node=8)`: walks each focal IP's
  depth-1 neighborhood, skipping severed edges, sorting `failed_from` and
  `contradicts` neighbors first, and formatting each as
  `[<edge_type>] →/← <neighbor_name> — <edge_note>`.
- New `_build_operator_prompt(op, idea, seed, node_ids)`: the single
  assembly path used by both `/apply_operator` and `/context/preview`.
  Returns `(prompt, trace_meta)` so the preview shows exactly what the
  model will receive.
- `/api/apply_operator` accepts new `node_ids: [str]` param. The existing
  keyword-based `_field_context` still runs as a complement; both are
  prepended to the prompt with separate clearly-labeled sections.
- The response now includes `topology_neighbors` count and a full `trace`
  object so the frontend can attach it to whatever artifact the call produces.

**Frontend** — `static/index.html`:
- `connModalGenerateFromOp`, `connModalGenerateCustom`, `generateConnections`
  all pass `[src, tgt]` as `node_ids`.
- `callOp` (the sequence/agent runner) passes the current
  `selectedIPIds` set if any IPs are selected when the call fires.
- Status text now shows topology + keyword hit counts:
  `✓ generated (topo:5 kw:3)`.

## 2. Context preview + retrieval log

You can now see the exact prompt before sending and re-inspect the prompt
after the artifact is created.

**New endpoints** — `server.py`:
- `POST /api/context/preview` — same body shape as `/apply_operator`;
  returns the assembled `trace_meta` without calling the LLM. Zero cost.
- `GET  /api/trace/<entity_id>` — fetch the stored `llm_trace` from an
  IP's or edge's `metadata`. 404 if none was stored.
- `PUT  /api/trace/<entity_id>` — attach a trace to an existing IP or edge.
  Called by the UI immediately after a successful generation.
- `POST /api/connect` now returns the new `edge_id` so the frontend can
  bind a trace to it.

**New UI** — `static/index.html`:
- **📋 Preview Context** button in the Add Connection modal (next to
  ✦ Custom Generate). Opens the trace modal pre-populated with the prompt
  that *would* be sent, including the topology neighbor list — no API call.
- **🔍 Trace** button on the IP and Edge detail panels. Appears only when
  a stored `llm_trace` exists for that entity. Opens the trace modal
  populated with prompt, neighbors used, response, model, and timestamp.
- **Trace modal** (`#trace-modal-overlay`) — shows a summary line (op,
  model, focal IPs, topology/keyword counts, prompt size, timestamp), the
  full topology-neighbor list with priority types colored red, the full
  prompt in a read-only textarea, and the response when available. Copy
  JSON button to grab the full trace for external inspection.

**Auto-attach flow:**
1. User clicks ✦ Custom Generate or an operator button in the conn modal.
2. Backend builds prompt with topology context, calls LLM, returns
   `{result, trace}`.
3. Frontend stashes `trace` in `pendingConnTrace`.
4. User clicks Save → POST `/connect` returns `edge_id` → frontend PUTs
   `pendingConnTrace` to `/api/trace/<edge_id>`.
5. The edge's `metadata.llm_trace` now holds the full generation record.
   Same flow for bulk `generateConnections`.

The trace stays bound to the edge across reloads — it's persisted in
`field_data.json` alongside the edge itself.

## Files Changed in v7

```
v7/
├── .env                  ← VERSION=v7
├── server.py             ← +_topology_context, +_build_operator_prompt,
│                            +/api/context/preview, +/api/trace/<id> (GET/PUT),
│                            /api/connect returns edge_id,
│                            /api/apply_operator accepts node_ids + returns trace
├── static/index.html     ← pass node_ids on all 4 LLM call sites,
│                            stash + auto-attach pendingConnTrace,
│                            📋 Preview Context button, 🔍 Trace buttons,
│                            #trace-modal-overlay + showTraceModal/viewTraceFor,
│                            version bump (title, badge, JS fallback)
└── CHANGELOG.md          ← this entry
```

## Migration from v82

```
copy C:\Users\Bozuron\stoe_engine\stoe_field_82\stoe_field_82\field_data.json C:\Users\Bozuron\stoe_engine\v7\field_data.json
copy C:\Users\Bozuron\stoe_engine\stoe_field_82\stoe_field_82\operators_custom.json C:\Users\Bozuron\stoe_engine\v7\operators_custom.json
```

No schema migration required. Old edges have no `metadata.llm_trace` and
simply show no 🔍 Trace button — only newly-generated edges from v7 onward
will have one.

## Where this came from

The two changes are direct ports of insights from `stoe_v3/`:

- `harness/context.py:TopologyContext.build()` — depth-1 walk with
  `[failed_from]` / `[contradicts]` surfacing. Same idea, in-app.
- `core/field.py:get_adjacent()` + `navigate_from()` — the same edge-walk
  primitives the harness uses for its benchmark. The navigator now uses
  them for every operator call.

What v7 does *not* yet port: structural evaluator (novelty/coherence/
bridging/attractor-distance), operator preconditions/refusals, Ghost-node
conservation of failed runs, embedding-based hybrid retrieval. These
remain candidates for v8+.

## 3. Agent answers no longer float disconnected (post-release fix)

In v82 the Agent flow created answer IPs via `/points` but never called
`/connect`. The result: every agent answer was a disconnected node — the
exact symptom that prompted this fix.

**Fix:**
- `runAgentLoop` now maintains an `agentSources` set, populated by
  `_harvestIpIds(toolResult)` after every `SEARCH` / `TOPOLOGY` /
  `ADJACENT` / `CATEGORY` / `PATH` / `DEADENDS` tool call.
- All three answer-save sites (ANSWER tag, prose-as-answer, max-steps
  fallback) now write `metadata.source_ips` on the new answer IP and
  call `_linkAgentAnswer(answerId, agentSources, userInput)`.
- `_linkAgentAnswer` creates `generated_by` edges from each source IP
  to the answer (capped at 6). If no tools were used, it falls back to
  a one-shot keyword search on the user query and links to the top 3 hits
  so the answer still lands inside the graph.
- Logged: `Answer linked to N/M source IP(s)`.

---

