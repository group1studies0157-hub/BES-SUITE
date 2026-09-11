"""
core/cell_sheet.py — Excel-like formula engine for BES input grids
═══════════════════════════════════════════════════════════════════

A tiny, dependency-free spreadsheet evaluator used by the GAD Generator's
phase-wise view builders (Elevation / Plan / Section / Wing & Return Wall /
Square Return).  The UI shows a 10x4 grid of cells; some cells carry
prefilled descriptions (RL:, FL:, HFL:, Linear Span:, BED LEVEL(BL):) and the
user types values — plain numbers or Excel-style formulas — in the cell to the
right of each description.

What the engine supports (mirrors the Excel subset field engineers use):

  * cell references        =B2, =A2+B3, =B2*B4*1000
  * arithmetic             + - * / ( ) and unary minus
  * ranges in functions    =SUM(B2:B4), =AVERAGE(B2:B5), =MIN(B2:B4)...
  * scalar functions       ABS, ROUND, SQRT, MAX, MIN, SUM, AVERAGE, IF
  * comparisons inside IF  =IF(B2>0, B3, B4)   (>, <, >=, <=, =, <>)
  * percent literals       =B2*5%              (5% -> 0.05)

Nothing else about a cell matters downstream — the code only consumes the
*computed numeric value* sitting against each description.
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Tuple

# A cell reference like $B$2, B2 or b12 (column letter(s) + row number)
_CELL_RE = re.compile(r"^\s*(\$?)([A-Z]{1,2})(\$?)(\d{1,4})\s*$", re.IGNORECASE)

# Name -> (callable, min_args, max_args)   max_args None = unlimited
_FUNCTIONS: Dict[str, Tuple[Callable, int, Optional[int]]] = {
    "SUM":     (lambda *a: sum(a),                              1, None),
    "AVERAGE": (lambda *a: sum(a) / len(a),                     1, None),
    "MIN":     (lambda *a: min(a),                              1, None),
    "MAX":     (lambda *a: max(a),                              1, None),
    "ABS":     (lambda a: abs(a),                               1, 1),
    "ROUND":   (lambda a, d=0: round(a, int(d)),                1, 2),
    "SQRT":    (lambda a: a ** 0.5,                             1, 1),
    "IF":      (lambda c, t, f: t if c else f,                  3, 3),
}


class SheetError(ValueError):
    """Raised for any user-visible formula problem (bad ref, cycle, syntax)."""


# ─────────────────────────────────────────────────────────────────────────────
# Cell-address helpers (letters <-> indexes; 1-based like Excel)
# ─────────────────────────────────────────────────────────────────────────────

def col_to_index(letters: str) -> int:
    """'A' -> 1, 'B' -> 2, ... 'Z' -> 26, 'AA' -> 27."""
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def index_to_col(idx: int) -> str:
    """1 -> 'A', 2 -> 'B', 27 -> 'AA'."""
    s = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        s = chr(ord("A") + rem) + s
    return s


def parse_cell(ref: str) -> Optional[Tuple[int, int]]:
    """'B3' -> (col=2, row=3); returns None when *ref* is not a cell address."""
    m = _CELL_RE.match(str(ref))
    if not m:
        return None
    return col_to_index(m.group(2)), int(m.group(4))


# ─────────────────────────────────────────────────────────────────────────────
# Tokenizer
# ─────────────────────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<cell>\$?[A-Za-z]{1,2}\$?\d{1,4})
    | (?P<pct>\d+(?:\.\d+)?%)                     # 5% -> 0.05
    | (?P<num>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
    | (?P<func>[A-Za-z_][A-Za-z_0-9]*\s*\()       # NAME(
    | (?P<op>[-+*/^()<>;,=:])
    """,
    re.VERBOSE,
)


def _tokenize(src: str) -> List[Tuple[str, str]]:
    """Return [(kind, text)] tokens; kinds: num, cell, func, op, cmp."""
    toks: List[Tuple[str, str]] = []
    i, n = 0, len(src)
    while i < n:
        m = _TOKEN_RE.match(src, i)
        if not m:
            raise SheetError(f"Unexpected character {src[i]!r} in formula")
        i = m.end()
        kind = m.lastgroup or ""
        text = m.group()
        if kind == "ws":
            continue
        if kind == "func":
            toks.append(("func", text[: text.index("(")].strip().upper()))
            toks.append(("op", "("))
        elif kind == "pct":
            toks.append(("num", str(float(text[:-1]) / 100.0)))
        elif kind == "op" and text in "<>=":
            # comparison operators: <  >  <=  >=  =  <>
            if text in "<>" and i < n and src[i] == "=":
                toks.append(("cmp", text + "="))
                i += 1
            elif text == "<" and i < n and src[i] == ">":
                toks.append(("cmp", "<>"))
                i += 1
            else:
                toks.append(("cmp", text))
        else:
            toks.append((kind, text))
    return toks


# ─────────────────────────────────────────────────────────────────────────────
# Recursive-descent parser (precedence: cmp < +,- < *,/ < power < unary < atom)
# ─────────────────────────────────────────────────────────────────────────────

class _Parser:
    def __init__(self, toks: List[Tuple[str, str]]):
        self.toks = toks
        self.pos = 0

    def _peek(self) -> Optional[Tuple[str, str]]:
        return self.toks[self.pos] if self.pos < len(self.toks) else None

    def _next(self) -> Tuple[str, str]:
        t = self._peek()
        if t is None:
            raise SheetError("Unexpected end of formula")
        self.pos += 1
        return t

    def _expect(self, text: str) -> None:
        k, v = self._next()
        if k != "op" or v != text:
            raise SheetError(f"Expected {text!r} in formula")

    def parse(self) -> float:
        val = self._comparison()
        if self._peek() is not None:
            raise SheetError(f"Unexpected token {self._peek()[1]!r}")
        return val

    def _comparison(self) -> float:
        val = self._additive()
        t = self._peek()
        if t and t[0] == "cmp":
            op = self._next()[1]
            rhs = self._additive()
            val = float({
                "<":  val <  rhs,
                ">":  val >  rhs,
                "<=": val <= rhs,
                ">=": val >= rhs,
                "=":  val == rhs,
                "<>": val != rhs,
            }[op])
        return val

    def _additive(self) -> float:
        val = self._term()
        while True:
            t = self._peek()
            if t and t[0] == "op" and t[1] in "+-":
                op = self._next()[1]
                rhs = self._term()
                val = val + rhs if op == "+" else val - rhs
            else:
                return val

    def _term(self) -> float:
        val = self._power()
        while True:
            t = self._peek()
            if t and t[0] == "op" and t[1] in "*/":
                op = self._next()[1]
                rhs = self._power()
                val = val * rhs if op == "*" else val / rhs
            else:
                return val

    def _power(self) -> float:
        val = self._unary()
        t = self._peek()
        if t and t[0] == "op" and t[1] == "^":
            self._next()
            return val ** self._power()
        return val

    def _unary(self) -> float:
        t = self._peek()
        if t and t[0] == "op" and t[1] in "+-":
            op = self._next()[1]
            v = self._unary()
            return v if op == "+" else -v
        return self._atom()

    def _atom(self) -> float:
        kind, text = self._next()
        if kind == "num":
            return float(text)
        if kind == "cell":
            return self._cell_value(text)
        if kind == "func":
            return self._call(text)
        if kind == "op" and text == "(":
            val = self._comparison()
            self._expect(")")
            return val
        if kind == "op" and text == ";":     # argument separator slip-through
            raise SheetError("Stray ';' — separate function args with ','")
        raise SheetError(f"Unexpected token {text!r} in formula")

    # -- overridable hooks (used by the evaluator for refs & ranges) --------
    def _cell_value(self, ref: str) -> float:
        raise SheetError(f"Cell reference {ref} not allowed here")

    def _call(self, name: str) -> float:
        fn, lo, hi = _FUNCTIONS.get(name, (None, 0, 0))
        if fn is None:
            raise SheetError(f"Unknown function {name}()")
        self._expect("(")
        args = self._parse_call_args()
        if len(args) < lo or (hi is not None and len(args) > hi):
            raise SheetError(f"{name}() takes {lo}"
                             + (f"-{hi}" if hi else "+") + " argument(s)")
        return float(fn(*args))

    def _parse_call_args(self) -> List[float]:
        """Parse args after the opening '(' — caller consumed it — up to and
        including the closing ')' (which is also consumed)."""
        args: List[float] = []
        if not (self._peek() and self._peek() == ("op", ")")):
            args.append(self._comparison())
            while self._peek() and self._peek()[0] == "op" and self._peek()[1] in ",;":
                self._next()
                args.append(self._comparison())
        self._expect(")")
        return args


# ─────────────────────────────────────────────────────────────────────────────
# Evaluator
# ─────────────────────────────────────────────────────────────────────────────

class CellSheet:
    """Holds raw cell contents and computes evaluated values on demand.

    Raw values are what the user typed: '' (empty), '123.4', '=B2*1000' or
    any text (descriptions like 'RL:' are simply non-numeric).  Formulas may
    reference other cells; circular references raise SheetError.
    """

    def __init__(self, raw: Optional[Dict[str, str]] = None):
        # keys are canonical 'B2'-style addresses (no $)
        self.raw: Dict[str, str] = {}
        self._cache: Dict[str, float] = {}
        self._visiting: set = set()
        for k, v in (raw or {}).items():
            self.set_raw(k, v)

    # -- population ----------------------------------------------------------
    def set_raw(self, ref: str, value: object) -> None:
        addr = self.canonical(ref)
        if addr is None:
            raise SheetError(f"Invalid cell address {ref!r}")
        self.raw[addr] = "" if value is None else str(value)
        self._cache.pop(addr, None)

    def canonical(self, ref: str) -> Optional[str]:
        pos = parse_cell(ref)
        if pos is None:
            return None
        col, row = pos
        return f"{index_to_col(col)}{row}"

    # -- evaluation ----------------------------------------------------------
    def value(self, ref: str) -> float:
        """Numeric value of a cell (0.0 when empty) — or of a bare '=...' 
        expression. Raises SheetError on cycles and bad formulas."""
        if isinstance(ref, str) and ref.startswith("="):
            return self._eval_formula(ref.strip(), "")
        addr = self.canonical(ref)
        if addr is None:
            raise SheetError(f"Invalid cell address {ref!r}")
        return self._eval(addr)

    def value_or_none(self, ref: str) -> Optional[float]:
        """Numeric value of a cell, or None when the cell is empty/text/broken."""
        addr = self.canonical(ref)
        if addr is None or not self.raw.get(addr, "").strip():
            return None
        raw = self.raw[addr].strip()
        if not raw.startswith("="):
            try:
                return float(raw.replace(",", ""))
            except ValueError:
                return None               # text cell (label / description)
        try:
            return self._eval(addr)
        except SheetError:
            return None

    def _eval(self, addr: str) -> float:
        if addr in self._cache:
            return self._cache[addr]
        raw = self.raw.get(addr, "").strip()
        if not raw:
            return 0.0
        if addr in self._visiting:
            raise SheetError(f"Circular reference involving {addr}")
        self._visiting.add(addr)
        try:
            val = self._eval_formula(raw, addr)
        finally:
            self._visiting.discard(addr)
        self._cache[addr] = val
        return val

    def _eval_formula(self, raw: str, addr: str) -> float:
        if raw.startswith("="):
            src = raw[1:]
        else:
            try:
                return float(raw.replace(",", ""))
            except ValueError:
                return 0.0        # text cell (description / label) -> 0
        parser = _RefParser(_tokenize(src), self, addr)
        return parser.parse()

    # -- helpers -------------------------------------------------------------
    def get_display(self, ref: str) -> str:
        """The raw text as typed — for putting back into a UI grid."""
        addr = self.canonical(ref) or str(ref)
        return self.raw.get(addr, "")

    def filled(self) -> List[str]:
        """Addresses of all non-empty cells, sorted A1-first."""
        def key(a: str):
            pos = parse_cell(a)
            return (pos[1], pos[0]) if pos else (0, 0)
        return sorted([a for a, v in self.raw.items() if v.strip()], key=key)


class _RefParser(_Parser):
    """Parser wired to a CellSheet so cell refs and ranges resolve."""

    _RANGE_RE = re.compile(r"^\s*(\$?[A-Z]{1,2}\$?\d{1,4})\s*:\s*"
                           r"(\$?[A-Z]{1,2}\$?\d{1,4})\s*$", re.IGNORECASE)

    def __init__(self, toks, sheet: "CellSheet", origin: str):
        super().__init__(toks)
        self.sheet = sheet
        self.origin = origin

    def _cell_value(self, ref: str) -> float:
        addr = self.sheet.canonical(ref)
        if addr is None:
            raise SheetError(f"Invalid cell reference {ref!r}")
        return self.sheet._eval(addr)

    def _call(self, name: str) -> float:
        # Range form first:  NAME(A1:B2) — expand to scalar args.
        self._expect("(")
        first = self._peek()
        if first and first[0] == "cell":
            start = self.pos
            f = self._next()
            if self._peek() == ("op", ":"):
                self._next()
                last = self._next()
                if last[0] == "cell":
                    m = self._RANGE_RE.match(f"{f[1]}:{last[1]}")
                    if m:
                        vals = [self._range_values(name, m.group(1), m.group(2))]
                        # mixed form: SUM(A1:A3, 4) — extra scalar args
                        while self._peek() and self._peek()[0] == "op" \
                                and self._peek()[1] in ",;":
                            self._next()
                            vals.append(self._comparison())
                        self._expect(")")
                        fn, lo, hi = _FUNCTIONS[name.upper()]
                        if len(vals) < lo or (hi is not None and len(vals) > hi):
                            raise SheetError(f"{name}() takes {lo}"
                                             + (f"-{hi}" if hi else "+")
                                             + " argument(s)")
                        return float(fn(*vals))
            self.pos = start          # not a range — rewind (after the '(')
            # '(' already consumed: parse scalar args directly, with arity check
            fn, lo, hi = _FUNCTIONS.get(name, (None, 0, 0))
            if fn is None:
                raise SheetError(f"Unknown function {name}()")
            args = self._parse_call_args()
            if len(args) < lo or (hi is not None and len(args) > hi):
                raise SheetError(f"{name}() takes {lo}"
                                 + (f"-{hi}" if hi else "+") + " argument(s)")
            return float(fn(*args))
        # Empty-parens or non-cell first arg: hand back to the base parser,
        # rewinding to just before the '(' it expects.
        self.pos -= 1
        return super()._call(name)

    def _range_values(self, name: str, a1: str, a2: str) -> float:
        """Fold a range through the function; raises for scalar-only fns."""
        vals = self._collect_range(a1, a2)
        fn, lo, hi = _FUNCTIONS[name.upper()]
        if hi is not None and hi == 1:
            raise SheetError(f"{name}() does not accept a range")
        if len(vals) < lo:
            raise SheetError(f"{name}() needs at least {lo} value(s)")
        return float(fn(*vals))

    def _collect_range(self, a1: str, a2: str) -> List[float]:
        p1, p2 = parse_cell(a1), parse_cell(a2)
        if p1 is None or p2 is None:
            raise SheetError(f"Bad range {a1}:{a2}")
        c0, r0 = p1
        c1, r1 = p2
        c0, c1 = min(c0, c1), max(c0, c1)
        r0, r1 = min(r0, r1), max(r0, r1)
        vals: List[float] = []
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                addr = f"{index_to_col(c)}{r}"
                v = self.sheet.value_or_none(addr)
                if v is not None:
                    vals.append(v)
        if not vals:
            raise SheetError(f"Empty range {a1}:{a2}")
        return vals

# (legacy range helper folded into _RefParser._call / _range_values)


# ─────────────────────────────────────────────────────────────────────────────
# Grid helpers used by the GAD view UIs
# ─────────────────────────────────────────────────────────────────────────────

GRID_ROWS, GRID_COLS = 4, 10          # 10 x 4 usable space (cols A..J, rows 1..4)


def grid_label(col: int, row: int) -> str:
    """0-based (col,row) -> Excel-style label, e.g. (1,0) -> 'B1'."""
    return f"{index_to_col(col + 1)}{row + 1}"


def collect_grid(grid_values: "list") -> "CellSheet":
    """Build a CellSheet from a 2-D list[row][col] of raw cell strings."""
    sh = CellSheet()
    for r, row_vals in enumerate(grid_values):
        for c, v in enumerate(row_vals):
            if v is None or str(v).strip() == "":
                continue
            sh.set_raw(grid_label(c, r), str(v))
    return sh


def extract_described_values(sheet: CellSheet,
                             descriptions: Dict[str, str]) -> Dict[str, Optional[float]]:
    """Find the value entered *against* each description label.

    The UI prefills description cells like 'RL:' / 'FL:' / 'HFL:' /
    'Linear Span:' / 'BED LEVEL(BL):'.  The user's value may be typed in the
    same cell after the text, in the cell to the right, below, or anywhere on
    the same row — we scan rightwards from the description cell, then the
    remaining cells of the row, and finally the cell directly below.

    Returns {key: value-or-None}.  *descriptions* maps output key -> any of
    the label spellings, e.g. {"RL": "RL:"}.

    Only the resolved numeric value matters to the drawing code.
    """
    # index description cells by normalised text
    norm = lambda s: re.sub(r"[\s.:_()\-]+", "", str(s).upper())
    by_addr = {a: norm(v) for a, v in sheet.raw.items() if v.strip()}
    want = {key: norm(label) for key, label in descriptions.items()}

    out: Dict[str, Optional[float]] = {k: None for k in descriptions}
    for key, wtext in want.items():
        if not wtext:
            continue
        # 1) description and value in the SAME cell:  "RL: 178.741"
        for addr, text in by_addr.items():
            if not text.startswith(wtext):
                continue
            raw = sheet.raw.get(addr, "")
            tail = raw[raw.upper().find(str(descriptions[key]).split(":")[0][:3]) + len(descriptions[key]):]
            tail = re.sub(r"^[\s.:_\-]+", "", tail).strip()
            if tail:
                try:
                    out[key] = float(tail.replace(",", ""))
                    break
                except ValueError:
                    pass
            # 2) value in a later cell of the same row, then directly below
            if out[key] is None:
                pos = parse_cell(addr)
                if pos:
                    col, row = pos
                    for c in range(col + 1, GRID_COLS + 1):
                        v = sheet.value_or_none(f"{index_to_col(c)}{row}")
                        if v is not None:
                            out[key] = v
                            break
                if out[key] is None:
                    below = sheet.value_or_none(f"{index_to_col(pos[0] if pos else 1)}{(pos[1] if pos else 1) + 1}")
                    if below is not None:
                        out[key] = below
            if out[key] is not None:
                break
    return out


if __name__ == "__main__":
    # self-test
    sh = CellSheet({
        "A1": "RL:",        "B1": "178.741",
        "A2": "FL:",        "B2": "=B1-0.762",
        "A3": "HFL:",       "B3": "176.877",
        "A4": "BED LEVEL(BL):", "B4": "175.877",
        "C1": "Linear Span:", "D1": "4.25",
        "E2": "=D1*1000",
    })
    vals = extract_described_values(sh, {
        "RL": "RL:", "FL": "FL:", "HFL": "HFL:", "BL": "BED LEVEL(BL):",
        "Linear Span": "Linear Span:",
    })
    assert abs(vals["RL"] - 178.741) < 1e-9, vals
    assert abs(vals["FL"] - 177.979) < 1e-9, vals
    assert abs(vals["BL"] - 175.877) < 1e-9, vals
    assert abs((sh.value("E2") or 0) - 4250.0) < 1e-9
    assert sh.value("=SUM(B1:B3)*0+42") == 42.0
    assert sh.value("=IF(B3>B4, 10, 20)") == 10.0
    sh2 = CellSheet({"A1": "=A1+1"})            # cycle
    try:
        sh2.value("A1")
        raise SystemExit("cycle not detected")
    except SheetError:
        pass
    print("cell_sheet self-tests PASSED")
