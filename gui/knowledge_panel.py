"""
Knowledge Base Panel — Bridge Engineering Suite v2.0
Tab 3: AI-powered Quiz App + Keyword Search Engine
Based on LDCE exam pattern analysis (PYQ subject-wise weightage)
"""

import os, json, random, datetime, re, time, base64
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QComboBox, QLineEdit, QTextEdit,
    QSplitter, QListWidget, QListWidgetItem, QProgressBar,
    QSizePolicy, QApplication, QFileDialog, QDialog,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings, QTimer
from PyQt6.QtGui import QFont, QColor, QPixmap

from gui.styles import COLORS
from gui.icons import icon_path as get_icon_path
from gui.ai_provider import (AIProvider, PROVIDERS, PROVIDER_ANTHROPIC,
                              PROVIDER_GEMINI, detect_provider,
                              ANTHROPIC_MODEL)

# ── Single source of truth for the model name is gui/ai_provider.py ──────────
CLAUDE_MODEL = ANTHROPIC_MODEL

# ── Database path helper ──────────────────────────────────────────────────────
def _db_dir():
    """
    Locate the Database folder.  Tries several layouts so it works wherever
    the project is installed. Creates the folder if it does not yet exist.
    """
    here  = os.path.dirname(os.path.abspath(__file__))   # .../gui/
    root  = os.path.dirname(here)                         # project root
    candidates = [
        os.path.join(root, "Database"),
        os.path.join(root, "database"),
        os.path.join(here, "database"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    path = candidates[0]
    os.makedirs(path, exist_ok=True)
    return path

def _qbank_path():
    return os.path.join(_db_dir(), "question_bank.json")

# ── Syllabus topics with PYQ weights ─────────────────────────────────────────
TOPICS = [
    # (display name, internal key, PYQ count 30%+70%, priority)
    ("IRPWM — Indian Railway Permanent Way Manual",     "IRPWM",              22, "⭐ Highest"),
    ("Bridges — Inspection, Maintenance & Rehabilitation","Bridges",           6,  "⭐ High"),
    ("IRBM — Indian Railway Bridge Manual",              "IRBM",               5,  "⭐ High"),
    ("Track Machines",                                   "TrackMachines",      8,  "🔹 High"),
    ("IRWM — Indian Railway Works Manual",               "IRWM",               8,  "🔹 High"),
    ("SOD / USFD",                                       "SOD_USFD",           2,  "🔸 Medium"),
    ("Establishment Rules",                              "Establishment",      18, "⭐ High"),
    ("Finance & Stores",                                 "Finance_Stores",     17, "⭐ High"),
    ("General Knowledge",                                "GeneralKnowledge",   40, "🔹 High"),
    ("Surveying & Levelling",                            "Surveying",          3,  "🔸 Medium"),
    ("Strength of Materials",                            "SOM",                4,  "🔸 Medium"),
    ("RCC, Concrete Technology & Steel Structures",      "RCC_Steel",          4,  "🔸 Medium"),
    ("Construction Materials",                           "ConstructionMat",    1,  "🔹 Low"),
    ("Soil Mechanics & Foundation Engineering",          "SoilMechanics",      3,  "🔸 Medium"),
    ("Hydraulics & Hydrology",                           "Hydraulics",         2,  "🔸 Medium"),
    ("Public Health Engineering",                        "PHE",                3,  "🔸 Medium"),
    ("Miscellaneous / Railway Working Rules",            "Miscellaneous",      21, "⭐ High"),
    ("Hindi / Rajbhasha Policy",                         "Hindi_Rajbhasha",   15,  "🔹 Medium"),
    ("🎲 Surprise Test — All Topics Random Mix",          "SurpriseTest",       0,  "🎯 Special"),
]

MOTIVATION_QUOTES = [
    "Every expert was once a beginner. Keep pushing — you've got this! 💪",
    "Struggle is the price of progress. Review your weak areas and try again! 📚",
    "Rome wasn't built in a day, and neither is exam success. Revise & retry! 🔄",
    "Don't count the mistakes — count the lessons. You're learning! 🌱",
    "The only failure is giving up. One more attempt, one step closer! 🚀",
    "Hard work beats talent when talent doesn't work hard. Keep grinding! ⚙️",
]

ENCOURAGEMENT_QUOTES = [
    "Outstanding performance! You're on track to ace the LDCE! 🏆",
    "Excellent work! Your dedication is clearly paying off! 🌟",
    "Brilliant! Keep this momentum going — success is yours! 🎯",
    "Superb effort! You're ready for the real examination hall! 🎖️",
    "Fantastic score! Your preparation is top-notch! 🥇",
    "Great job! You're mastering the syllabus one topic at a time! ✅",
]


# ── Worker: AI Question Generator ─────────────────────────────────────────────
class QuizWorker(QThread):
    questions_ready = pyqtSignal(list)  # list of question dicts
    error           = pyqtSignal(str)
    status          = pyqtSignal(str)

    def __init__(self, topic_key, topic_name, api_key="", count=10, provider="",
                 gemini_key="", claude_key=""):
        super().__init__()
        self.topic_key   = topic_key
        self.topic_name  = topic_name
        self.count       = count
        # Dual-key support: prefer explicit gemini_key/claude_key; fall back to
        # legacy single api_key for backward-compatibility
        self._gemini_key = gemini_key or (api_key if api_key.startswith("AIza") else "")
        self._claude_key = claude_key or (api_key if api_key.startswith("sk-ant") else "") or api_key
        # Kept for _extract_pdf_context compatibility
        self.api_key     = gemini_key or claude_key or api_key
        self.provider    = provider or ("dual" if (gemini_key and claude_key) else
                           detect_provider(self.api_key))

    def _build_ai(self):
        """Return the right AIProvider for the current key configuration."""
        gk, ck = self._gemini_key, self._claude_key
        if gk and ck:
            return AIProvider.dual(gk, ck), "Gemini→Claude"
        if gk:
            return AIProvider(gk, PROVIDER_GEMINI), "Gemini"
        return AIProvider(ck, PROVIDER_ANTHROPIC), "Claude"

    def run(self):
        try:
            ai, pname = self._build_ai()
            self.status.emit(
                f"🤖 {pname} AI generating {self.count} questions on {self.topic_name}..."
            )

            # ── Step 1: Try PDF context first ────────────────────────────
            pdf_context = self._extract_pdf_context()

            # ── Step 2: Build prompt ──────────────────────────────────────
            base_prompt = f"""You are an expert examiner for LDCE (Limited Departmental Competitive Examination)
for Indian Railways Junior Engineers / Senior Section Engineers promotion exam.

Generate exactly {self.count} high-quality MCQ questions on the topic: **{self.topic_name}**

Exam context:
- LDCE Railway exam: CBT format, 1 mark each, -1/3 negative marking
- Questions must be based on actual IRPWM, IRBM, IRWM, SOD codes and railway manuals
- This year heavy focus on: Strength of Materials, RCC, Concrete, Steel Structures,
  Fluid Mechanics, Hydraulics — include questions from these if relevant to topic
- Mix difficulty: 40% easy, 40% medium, 20% hard
- Focus on numerical values, definitions, schedules, specifications from railway codes
- If the question is based on an actual LDCE/departmental exam question, include the exam year in pyq_year field

Return ONLY a valid JSON array. The array MUST be complete and properly closed. No markdown, no extra text:
[
  {{
    "question": "Full question text here",
    "options": ["Option A text", "Option B text", "Option C text", "Option D text"],
    "correct": 0,
    "explanation": "Brief explanation citing source code/chapter",
    "difficulty": "easy|medium|hard",
    "source": "e.g. IRPWM Para 519 / IS 456:2000",
    "pyq_year": "2023" 
  }}
]
Rules:
- correct is 0-indexed (0=A, 1=B, 2=C, 3=D)
- All 4 options must be plausible
- Cite rule/para numbers in source
- pyq_year: use the actual exam year (e.g. "2023", "2021") if it is a known PYQ; omit or use null otherwise
- IMPORTANT: Ensure the JSON array is complete and properly terminated with ]"""

            if pdf_context:
                self.status.emit(
                    f"📄 {pname} reading PDF source + generating {self.count} questions..."
                )
                prompt = (f"PDF SOURCE MATERIAL:\n---\n{pdf_context[:4000]}\n---\n\n"
                          + base_prompt)
            else:
                prompt = base_prompt

            raw = ai.chat(system="You are a railway engineering exam question generator. "
                                  "Return only valid JSON arrays, no markdown.",
                          user=prompt, max_tokens=4000)

            raw = re.sub(r"```json|```", "", raw).strip()

            # ── Robust JSON recovery ──────────────────────────────────────
            # AI responses sometimes truncate mid-JSON causing parse errors.
            # Try progressively more aggressive repairs before giving up.
            questions = None
            parse_error = None

            # Attempt 1: direct parse
            try:
                questions = json.loads(raw)
            except json.JSONDecodeError as e:
                parse_error = e

            # Attempt 2: extract the JSON array portion only
            if questions is None:
                try:
                    start = raw.find("[")
                    end   = raw.rfind("]")
                    if start != -1 and end != -1 and end > start:
                        questions = json.loads(raw[start:end+1])
                except json.JSONDecodeError:
                    pass

            # Attempt 3: truncate at last complete object boundary
            if questions is None:
                try:
                    # Find last complete "}" before a "," or "]"
                    truncated = raw[:raw.rfind("}") + 1]
                    if not truncated.strip().startswith("["):
                        truncated = "[" + truncated
                    truncated = truncated.rstrip().rstrip(",") + "]"
                    questions = json.loads(truncated)
                except json.JSONDecodeError:
                    pass

            # Attempt 4: use regex to extract individual question objects
            if questions is None:
                try:
                    obj_matches = re.findall(
                        r'\{[^{}]*"question"[^{}]*"options"[^{}]*"correct"[^{}]*\}',
                        raw, re.DOTALL)
                    if obj_matches:
                        questions = [json.loads(m) for m in obj_matches
                                     if self._safe_json(m)]
                except Exception:
                    pass

            if not questions:
                raise ValueError(
                    f"AI returned unparseable JSON. "
                    f"Original error: {parse_error}. "
                    f"Raw response (first 300 chars): {raw[:300]}"
                )

            for q in questions:
                q["topic"]   = self.topic_key
                q["created"] = datetime.date.today().isoformat()
                q["origin"]  = f"ai_{pname.lower()}"
            self.questions_ready.emit(questions)
        except Exception as e:
            self.error.emit(str(e))

    def _safe_json(self, s):
        """Return True if s is valid JSON."""
        try:
            json.loads(s)
            return True
        except Exception:
            return False

    def _extract_pdf_context(self):
        """
        Try to extract relevant text from PDFs in the Database folder
        for the current topic.  Returns a string (possibly empty).
        """
        try:
            import fitz
        except ImportError:
            return ""
        try:
            db   = _db_dir()
            pdfs = [f for f in os.listdir(db) if f.lower().endswith(".pdf")]
            if not pdfs:
                return ""

            # Keywords that help pick pages relevant to this topic
            topic_lower = self.topic_key.lower()
            kw_map = {
                "bridges":          ["bridge", "girder", "abutment", "pier", "scour"],
                "irbm":             ["bridge", "irbm", "inspection", "girder"],
                "irpwm":            ["irpwm", "track", "rail", "sleeper", "ballast"],
                "irwm":             ["irwm", "works", "building", "drainage"],
                "sod_usfd":         ["sod", "usfd", "dimension", "clearance", "gauge"],
                "trackmachines":    ["machine", "tamping", "ballast", "regulator"],
                "establishment":    ["establishment", "service", "leave", "pay"],
                "finance_stores":   ["finance", "store", "purchase", "account"],
                "generalknowledge": ["general", "railway", "india"],
                "surveying":        ["survey", "level", "theodolite", "contour"],
                "som":              ["stress", "strain", "beam", "moment", "shear"],
                "rcc_steel":        ["rcc", "concrete", "steel", "reinforcement"],
                "constructionmat":  ["material", "cement", "aggregate", "brick"],
                "soilmechanics":    ["soil", "foundation", "bearing", "settlement"],
                "hydraulics":       ["hydraulic", "flow", "pipe", "channel", "flood"],
                "phe":              ["sanitation", "water", "sewage", "chlorine"],
                "miscellaneous":    ["rule", "railway", "working", "general"],
                "hindi_rajbhasha":  ["hindi", "rajbhasha", "language", "official"],
            }
            keywords = kw_map.get(topic_lower, [self.topic_key.lower()])

            collected = []
            for pdf_name in pdfs:
                pdf_path = os.path.join(db, pdf_name)
                try:
                    doc = fitz.open(pdf_path)
                    for page_no in range(min(len(doc), 300)):  # cap for speed
                        text = doc[page_no].get_text()
                        tl   = text.lower()
                        if any(k in tl for k in keywords):
                            collected.append(text)
                        if len("\n".join(collected)) > 4000:
                            break
                    doc.close()
                except Exception:
                    continue
                if len("\n".join(collected)) > 4000:
                    break

            return "\n\n".join(collected)[:4000]
        except Exception:
            return ""


# ── Search Index helpers ───────────────────────────────────────────────────────
def _index_path():
    return os.path.join(_db_dir(), "_search_index.sqlite")

def _index_needs_rebuild():
    """Return True when any PDF is newer than the index, or index is missing."""
    idx = _index_path()
    if not os.path.exists(idx):
        return True
    idx_mtime = os.path.getmtime(idx)
    db = _db_dir()
    for f in os.listdir(db):
        if f.lower().endswith(".pdf"):
            if os.path.getmtime(os.path.join(db, f)) > idx_mtime:
                return True
    return False

def _open_index_db():
    """Open (or create) the SQLite FTS5 index and return the connection."""
    import sqlite3
    conn = sqlite3.connect(_index_path(), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pages (
            id       INTEGER PRIMARY KEY,
            pdf      TEXT NOT NULL,
            pdf_path TEXT NOT NULL,
            page_no  INTEGER NOT NULL,
            heading  TEXT,
            text     TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts
        USING fts5(text, heading, content='pages', content_rowid='id',
                   tokenize='unicode61 remove_diacritics 2')
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)
    """)
    conn.commit()
    return conn


# ── Worker: Index Builder ──────────────────────────────────────────────────────
class IndexWorker(QThread):
    progress = pyqtSignal(str)   # status messages
    finished = pyqtSignal(int)   # total pages indexed
    error    = pyqtSignal(str)

    def run(self):
        try:
            import fitz
        except ImportError:
            self.error.emit("PyMuPDF not installed. Run: pip install PyMuPDF")
            return
        try:
            import sqlite3
            db   = _db_dir()
            pdfs = [f for f in os.listdir(db) if f.lower().endswith(".pdf")]
            if not pdfs:
                self.error.emit("No PDF files found in Database folder.")
                return

            conn = _open_index_db()
            # Full rebuild — wipe existing rows
            conn.execute("DELETE FROM pages")
            conn.execute("DELETE FROM pages_fts")
            conn.commit()

            total = 0
            for pdf_name in pdfs:
                pdf_path = os.path.join(db, pdf_name)
                self.progress.emit(f"📄 Indexing {pdf_name}…")
                try:
                    doc = fitz.open(pdf_path)
                    batch = []
                    for page_no in range(len(doc)):
                        text = doc[page_no].get_text()
                        if not text.strip():
                            continue
                        lines   = text.split("\n")
                        heading = ""
                        for ln in lines:
                            ln = ln.strip()
                            if 6 < len(ln) < 80 and ln[0].isupper():
                                heading = ln
                                break
                        batch.append((pdf_name, pdf_path, page_no,
                                      heading or f"Page {page_no+1}", text))
                    doc.close()

                    # Insert in one transaction per PDF for speed
                    conn.executemany(
                        "INSERT INTO pages(pdf, pdf_path, page_no, heading, text) "
                        "VALUES (?,?,?,?,?)", batch
                    )
                    conn.commit()

                    # Rebuild FTS for this batch
                    conn.execute("INSERT INTO pages_fts(pages_fts) VALUES('rebuild')")
                    conn.commit()
                    total += len(batch)
                    self.progress.emit(
                        f"✅ {pdf_name}: {len(batch)} pages indexed  (total: {total})")
                except Exception as e:
                    self.progress.emit(f"⚠️  Skipped {pdf_name}: {e}")
                    continue

            # Stamp rebuild time
            conn.execute("INSERT OR REPLACE INTO meta VALUES('built_at', ?)",
                         (str(os.path.getmtime(_index_path())),))
            conn.commit()
            conn.close()
            self.finished.emit(total)
        except Exception as e:
            self.error.emit(str(e))


# ── Worker: PDF Search Engine (FTS5 + fallback linear scan) ───────────────────
class SearchWorker(QThread):
    results_ready = pyqtSignal(list)
    content_ready = pyqtSignal(str)
    error         = pyqtSignal(str)
    status        = pyqtSignal(str)

    MODE_SEARCH = "search"
    MODE_FETCH  = "fetch"

    def __init__(self, mode, keyword="", fetch_ref=None):
        super().__init__()
        self.mode      = mode
        self.keyword   = keyword
        self.fetch_ref = fetch_ref

    def run(self):
        try:
            import fitz
        except ImportError:
            self.error.emit("PyMuPDF not installed. Run: pip install PyMuPDF")
            return

        if self.mode == self.MODE_SEARCH:
            self._do_search(fitz)
        else:
            self._do_fetch(fitz)

    # ── FTS5 indexed search (instant) — supports comma-separated keywords ────────
    def _do_search(self, fitz):
        import sqlite3
        raw = self.keyword.strip()
        if not raw:
            return

        # ── Parse comma-separated keywords ───────────────────────────────────
        # self.keyword may carry "AND" or "OR" mode prefix set by the UI:
        #   "AND:term1,term2,term3"  →  page must contain ALL terms
        #   "OR:term1,term2,term3"   →  page must contain ANY term  (default)
        mode = "OR"
        if raw.upper().startswith("AND:"):
            mode = "AND"
            raw  = raw[4:]
        elif raw.upper().startswith("OR:"):
            raw  = raw[3:]

        # Split on commas, strip whitespace, drop empties
        terms = [t.strip() for t in raw.split(",") if t.strip()]
        if not terms:
            return

        display_kw = ", ".join(terms)

        # ── Try FTS5 index first ──────────────────────────────────────────────
        if os.path.exists(_index_path()):
            try:
                conn = sqlite3.connect(_index_path(), check_same_thread=False)
                conn.row_factory = sqlite3.Row

                # Build FTS5 MATCH expression
                # Each term is double-quoted so special chars are safe.
                # AND mode: "term1" AND "term2" AND ...
                # OR  mode: "term1" OR  "term2" OR  ...
                joiner    = f" {mode} "
                fts_query = joiner.join(f'"{t}"' for t in terms)

                rows = conn.execute("""
                    SELECT p.id, p.pdf, p.pdf_path, p.page_no, p.heading, p.text,
                           rank
                    FROM pages_fts f
                    JOIN pages p ON p.id = f.rowid
                    WHERE pages_fts MATCH ?
                    ORDER BY rank
                    LIMIT 100
                """, (fts_query,)).fetchall()
                conn.close()

                if rows:
                    results = []
                    for row in rows:
                        text     = row["text"]
                        tl       = text.lower()
                        # For AND mode: skip pages not containing ALL terms
                        if mode == "AND":
                            if not all(t.lower() in tl for t in terms):
                                continue
                        # Find best snippet: position of first matching term
                        best_idx = len(text)
                        for t in terms:
                            pos = tl.find(t.lower())
                            if pos != -1 and pos < best_idx:
                                best_idx = pos
                        if best_idx == len(text):
                            best_idx = 0
                        start   = max(0, best_idx - 120)
                        end     = min(len(text), best_idx + 220)
                        snippet = "…" + text[start:end].replace("\n", " ").strip() + "…"
                        results.append({
                            "pdf":      row["pdf"],
                            "pdf_path": row["pdf_path"],
                            "page":     row["page_no"],
                            "heading":  row["heading"] or f"Page {row['page_no']+1}",
                            "snippet":  snippet,
                            "terms":    terms,   # passed to content panel for highlight
                        })
                    if results:
                        self.status.emit(
                            f"⚡ {len(results)} results  [{mode}]  for: {display_kw}")
                        self.results_ready.emit(results)
                        return
                self.status.emit(
                    f"🔍 No FTS hits — scanning PDFs for: {display_kw}…")
            except Exception as e:
                self.status.emit(f"⚠️  Index error ({e}) — falling back to scan…")

        # ── Fallback: linear page-by-page scan ───────────────────────────────
        db        = _db_dir()
        pdf_files = ([f for f in os.listdir(db) if f.lower().endswith(".pdf")]
                     if os.path.isdir(db) else [])
        self.status.emit(
            f"🔍 Scanning PDFs  [{mode}]  for: {display_kw}…")
        results  = []
        for pdf_name in pdf_files:
            pdf_path = os.path.join(db, pdf_name)
            try:
                doc = fitz.open(pdf_path)
                for page_no in range(len(doc)):
                    text = doc[page_no].get_text()
                    tl   = text.lower()
                    # AND: all terms present; OR: any term present
                    if mode == "AND":
                        hit = all(t.lower() in tl for t in terms)
                    else:
                        hit = any(t.lower() in tl for t in terms)
                    if not hit:
                        continue
                    best_idx = len(text)
                    for t in terms:
                        pos = tl.find(t.lower())
                        if pos != -1 and pos < best_idx:
                            best_idx = pos
                    if best_idx == len(text): best_idx = 0
                    start   = max(0, best_idx - 120)
                    end     = min(len(text), best_idx + 220)
                    snippet = "…" + text[start:end].replace("\n"," ").strip() + "…"
                    lines   = text.split("\n")
                    heading = ""
                    for ln in lines:
                        ln = ln.strip()
                        if 6 < len(ln) < 80 and ln[0].isupper():
                            heading = ln; break
                    results.append({
                        "pdf":      pdf_name,
                        "pdf_path": pdf_path,
                        "page":     page_no,
                        "heading":  heading or f"Page {page_no+1}",
                        "snippet":  snippet,
                        "terms":    terms,
                    })
                    if len(results) >= 60: break
                doc.close()
            except Exception:
                continue
            if len(results) >= 60: break
        self.results_ready.emit(results)

    # ── Fetch page content for selected result — local only, no API ─────────────
    def _do_fetch(self, fitz):
        pdf_path, page_no, topic_hint = self.fetch_ref
        self.status.emit(f"📖 Extracting content from page {page_no+1}…")
        try:
            doc      = fitz.open(pdf_path)
            start    = max(0, page_no - 1)
            end      = min(len(doc), page_no + 3)
            combined = "\n\n".join(doc[p].get_text() for p in range(start, end))
            doc.close()
            self.content_ready.emit(combined[:3000])
        except Exception as e:
            self.error.emit(str(e))


# ── Question Bank persistence ─────────────────────────────────────────────────
def load_qbank():
    """Load question bank from disk.  If it doesn't exist yet, seed it
    from SEED_BANK so the quiz works immediately without any API call."""
    path = _qbank_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                bank = json.load(f)
            # Merge-in any seed questions not yet in the file
            _merge_seed(bank)
            return bank
        except Exception:
            pass
    # First run — build from seed
    bank = {"version": "1.0", "topics": {}}
    _merge_seed(bank)
    try:
        save_qbank(bank)
    except Exception:
        pass
    return bank

def _merge_seed(bank):
    """Silently add any SEED_BANK questions not already in bank (by text)."""
    for topic_key, seed_qs in SEED_BANK.items():
        existing = bank["topics"].setdefault(topic_key, [])
        existing_texts = {q["question"].strip().lower() for q in existing}
        for sq in seed_qs:
            if sq["question"].strip().lower() not in existing_texts:
                existing.append(sq)
                existing_texts.add(sq["question"].strip().lower())

def save_qbank(bank):
    path = _qbank_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(bank, f, indent=2, ensure_ascii=False)

def append_questions(topic_key, new_qs):
    bank = load_qbank()
    existing = bank["topics"].setdefault(topic_key, [])
    # Deduplicate by question text
    existing_texts = {q["question"].strip().lower() for q in existing}
    added = 0
    for q in new_qs:
        if q["question"].strip().lower() not in existing_texts:
            existing.append(q)
            existing_texts.add(q["question"].strip().lower())
            added += 1
    save_qbank(bank)
    return added

def get_cached_questions(topic_key, count=10):
    """
    Smart question selection engine.
    
    Rules:
    - Every question is tracked with an attempt count stored in the bank JSON.
    - MAX REPEAT RATE = 2: a question will not be shown a 3rd time until ALL
      questions in the topic have been seen at least once.
    - Priority order for selection:
        1. Never-seen questions  (attempt_count == 0)  — highest priority
        2. Seen-once questions   (attempt_count == 1)  — second priority  
        3. Seen-twice questions  (attempt_count == 2)  — only when 1 & 2 exhausted
    - Within each priority tier, questions are shuffled randomly.
    - After selection, attempt counts are incremented and saved immediately.
    """
    MAX_REPEATS = 2

    bank = load_qbank()
    pool = bank["topics"].get(topic_key, [])
    if not pool:
        return []

    # Ensure every question has an attempt_count field
    dirty = False
    for q in pool:
        if "attempt_count" not in q:
            q["attempt_count"] = 0
            dirty = True
    if dirty:
        save_qbank(bank)

    # Bucket questions by priority
    unseen   = [q for q in pool if q["attempt_count"] == 0]
    once     = [q for q in pool if q["attempt_count"] == 1]
    twice    = [q for q in pool if q["attempt_count"] == 2]
    # Questions seen > 2 times are only used as last resort
    overage  = [q for q in pool if q["attempt_count"] > 2]

    # Check if all questions have been seen at least once
    all_seen_once = len(unseen) == 0

    # Build ordered candidate list:
    # Never seen → once → twice → overage (only if bank is tiny)
    # Within each bucket, PYQ questions come first
    def _pyq_sort_key(q):
        """PYQ questions (PYQ_seed origin or pyq_year set) sort before AI-generated."""
        is_pyq = (q.get("origin", "").startswith("PYQ") or
                  q.get("pyq_year") or
                  q.get("pyq_date"))
        return (0 if is_pyq else 1)

    unseen.sort(key=_pyq_sort_key)
    once.sort(key=_pyq_sort_key)
    twice.sort(key=_pyq_sort_key)
    overage.sort(key=_pyq_sort_key)

    # Within same PYQ priority, shuffle for variety
    import itertools
    def _pyq_shuffle(lst):
        pyq = [q for q in lst if _pyq_sort_key(q) == 0]
        rest = [q for q in lst if _pyq_sort_key(q) == 1]
        random.shuffle(pyq)
        random.shuffle(rest)
        return pyq + rest

    unseen  = _pyq_shuffle(unseen)
    once    = _pyq_shuffle(once)
    twice   = _pyq_shuffle(twice)
    overage = _pyq_shuffle(overage)

    if all_seen_once:
        # All questions seen at least once — now allow repeats up to MAX_REPEATS
        candidates = once + twice + overage
    else:
        # Prefer unseen first; only pull from seen if unseen runs out
        candidates = unseen + once

        # If still not enough, fill remaining from twice (limited repeats)
        if len(candidates) < count:
            candidates += twice

    # Take the requested count (or all available)
    selected = candidates[:count]

    # Increment attempt_count for selected questions in the bank
    selected_texts = {q["question"].strip().lower() for q in selected}
    for q in pool:
        if q["question"].strip().lower() in selected_texts:
            q["attempt_count"] = q.get("attempt_count", 0) + 1

    # Save updated counts back to bank (no new questions — just counts updated)
    save_qbank(bank)

    # Return copies so UI doesn't hold references to bank objects
    import copy
    return copy.deepcopy(selected)


def get_surprise_test_questions(count=10):
    """
    Surprise Test: pulls questions from ALL topics randomly.

    Priority rules (same spirit as get_cached_questions but cross-topic):
      1. PYQ questions come first (pyq_year / PYQ origin), ordered by recency.
      2. Within PYQ tier: never-attempted questions first, then seen-once, etc.
      3. Within non-PYQ tier: same unseen-first ordering.
      4. Within each sub-tier, random shuffle for variety.

    After selection, attempt counts are incremented across all affected topics.
    """
    import copy, random as _rnd

    REAL_TOPICS = [key for _, key, _, _ in TOPICS if key != "SurpriseTest"]
    bank = load_qbank()

    # Ensure all questions have attempt_count
    dirty = False
    for tk in REAL_TOPICS:
        for q in bank["topics"].get(tk, []):
            if "attempt_count" not in q:
                q["attempt_count"] = 0
                dirty = True
    if dirty:
        save_qbank(bank)

    def _is_pyq(q):
        return (q.get("origin","").startswith("PYQ") or
                bool(q.get("pyq_year")) or bool(q.get("pyq_date")))

    def _pyq_sort_year(q):
        """Sort key: PYQ first (0), then by year desc (higher year = lower sort val)."""
        yr = q.get("pyq_year") or ""
        try:
            yr_int = int(str(yr)[:4])
        except Exception:
            yr_int = 0
        return (0 if _is_pyq(q) else 1, -yr_int)

    # Gather all questions across topics, tag with topic
    all_questions = []
    for tk in REAL_TOPICS:
        for q in bank["topics"].get(tk, []):
            qc = copy.copy(q)
            qc["_topic_key"] = tk
            all_questions.append(qc)

    if not all_questions:
        return []

    # Separate PYQ vs non-PYQ
    pyqs  = [q for q in all_questions if _is_pyq(q)]
    rest  = [q for q in all_questions if not _is_pyq(q)]

    def _bucket_sort(lst):
        """Sort list: unseen first, then once, then twice+; within each sub-group shuffle."""
        unseen  = [q for q in lst if q.get("attempt_count", 0) == 0]
        once    = [q for q in lst if q.get("attempt_count", 0) == 1]
        twice   = [q for q in lst if q.get("attempt_count", 0) == 2]
        over    = [q for q in lst if q.get("attempt_count", 0) > 2]
        _rnd.shuffle(unseen); _rnd.shuffle(once)
        _rnd.shuffle(twice);  _rnd.shuffle(over)
        return unseen + once + twice + over

    # Sort PYQs by year desc, then by attempt bucket
    pyqs.sort(key=_pyq_sort_year)
    # Group PYQs by year tier and bucket-sort within each year group
    pyq_bucketed = _bucket_sort(pyqs)

    rest_bucketed = _bucket_sort(rest)

    candidates = pyq_bucketed + rest_bucketed
    selected   = candidates[:count]

    # Increment attempt_count back into the real bank
    selected_texts = {q["question"].strip().lower() for q in selected}
    for tk in REAL_TOPICS:
        for q in bank["topics"].get(tk, []):
            if q["question"].strip().lower() in selected_texts:
                q["attempt_count"] = q.get("attempt_count", 0) + 1
    save_qbank(bank)

    # Strip internal tag, return deep copies
    result = []
    for q in selected:
        qc = copy.deepcopy(q)
        qc.pop("_topic_key", None)
        result.append(qc)
    return result


def get_topic_progress(topic_key):
    """
    Returns a dict with attempt statistics for the topic.
    Used by the quiz UI to show coverage progress.
    """
    bank = load_qbank()
    pool = bank["topics"].get(topic_key, [])
    if not pool:
        return {"total": 0, "unseen": 0, "seen_once": 0, "seen_twice": 0, "over": 0}
    return {
        "total":      len(pool),
        "unseen":     sum(1 for q in pool if q.get("attempt_count", 0) == 0),
        "seen_once":  sum(1 for q in pool if q.get("attempt_count", 0) == 1),
        "seen_twice": sum(1 for q in pool if q.get("attempt_count", 0) == 2),
        "over":       sum(1 for q in pool if q.get("attempt_count", 0) > 2),
    }



# ── Seed Question Bank — built from PYQ analysis of main_file.pdf ─────────────
# Auto-merged into question_bank.json on first run. Grows with API-generated Qs.
SEED_BANK = {
    "Bridges": [
        {"question": "A CRN of '6', given after inspection of a bridge, indicates ___", "options": ["Bridge in sound condition", "Bridge not existing", "Inspection not done", "Inspection not applicable"], "correct": 3, "explanation": "CRN 6 means the bridge component/element is not applicable for that bridge type \u2014 it is not inspected.", "difficulty": "easy", "source": "IRBM / Bridge Inspection Manual"},
        {"question": "Drop and curtain wall is provided ___", "options": ["To reduce velocity of water flow", "To reduce scouring effect of the stream", "To reduce settlement of bridge", "None of these"], "correct": 1, "explanation": "Drop & curtain walls are protection works at bridge foundations to prevent scour and erosion caused by flowing water.", "difficulty": "easy", "source": "IRBM \u2014 Bridge Protection Works"},
        {"question": "What is the most likely cause for 'leaning of parapet wall' in a masonry arch bridge?", "options": ["Settlement of abutment", "Weakness in masonry mortar", "Excessive back pressure on parapet", "Excessive longitudinal forces on bridge"], "correct": 2, "explanation": "Parapet walls lean outward due to earth pressure (back pressure) acting on the parapet, especially when fill material expands with moisture.", "difficulty": "medium", "source": "IRBM \u2014 Arch Bridge Defects"},
        {"question": "Select the most critical crack in arch bridges", "options": ["Transverse crack in arch barrel", "Longitudinal crack in arch barrel", "Crack in spandrel wall", "None of these"], "correct": 0, "explanation": "Transverse cracks in arch barrel are most critical as they indicate failure of the arch ring, potentially leading to collapse.", "difficulty": "medium", "source": "IRBM \u2014 Arch Bridge Defects"},
        {"question": "The horizontal and vertical spacing of weep holes provided in the bridge abutment is ___", "options": ["1.0 m", "0.9 m", "0.8 m", "0.7 m"], "correct": 0, "explanation": "As per bridge engineering practice and IRBM, weep holes in abutments are spaced at 1.0 m both horizontally and vertically to drain retained water effectively.", "difficulty": "easy", "source": "IRBM \u2014 Abutment Design"},
        {"question": "Bulging of abutment may be due to ___", "options": ["Excessive surcharge with increased axle load", "Chocked weep holes", "Failure of back fill material due to clogging", "All of these"], "correct": 3, "explanation": "All three \u2014 excess surcharge, blocked weep holes increasing pore pressure, and failed back fill \u2014 can cause abutment bulging.", "difficulty": "medium", "source": "IRBM \u2014 Abutment Maintenance"},
        {"question": "If during more than one consecutive inspection of any bridge by ADEN, the CRN of any component is recorded as 'Zero' then ___", "options": ["Bridge should be referred to Divisional Engineer for further orders", "Bridge should be closed immediately", "Bridge should be given emergency repairs", "ADEN should increase inspection frequency"], "correct": 0, "explanation": "CRN Zero indicates extreme distress. When recorded in consecutive inspections, the matter must be referred to DEN for further orders as per IRBM.", "difficulty": "medium", "source": "IRBM \u2014 Inspection Procedure"},
        {"question": "Catch water drain should be provided on the location of ___", "options": ["Upper slope of hill area to intercept and collect water flowing towards formation", "Along the side of railway formation", "Across the track", "None of these"], "correct": 0, "explanation": "Catch water drains are provided on the upper hill slopes to intercept and divert rainwater before it reaches the railway formation.", "difficulty": "easy", "source": "IRPWM \u2014 Drainage"},
        {"question": "Most important criterion to decide the bed gradient of the side water drain cutting is ___", "options": ["To be cheapest", "To be of locally available material", "To achieve self-cleansing velocity", "To be easily maintainable"], "correct": 2, "explanation": "Bed gradient must be sufficient to achieve self-cleansing velocity so that silt and debris do not accumulate in the drain.", "difficulty": "medium", "source": "IRPWM \u2014 Drainage Design"},
        {"question": "Bridge inspection by ADEN is done ___", "options": ["Once in 6 months", "Once a year", "Before every monsoon", "Every year after monsoon"], "correct": 3, "explanation": "As per IRPWM, bridges are inspected by ADEN every year after monsoon to assess any flood damage.", "difficulty": "easy", "source": "IRPWM Para 1605 \u2014 Bridge Inspection"},
        {"question": "The nominal size of stone used for pitching in railway bridges should not exceed ___", "options": ["150 mm", "200 mm", "250 mm", "300 mm"], "correct": 1, "explanation": "As per bridge protection standards, stone pitching material should not exceed 200 mm nominal size for effective interlocking.", "difficulty": "hard", "source": "IRBM \u2014 Bridge Protection Works"},
        {"question": "Bentonite slurry is used in pile driving for ___", "options": ["Stabilizing the bore hole walls", "Increasing workability of concrete", "Preventing segregation of concrete", "Preventing corrosion of reinforcement"], "correct": 0, "explanation": "Bentonite slurry is a thixotropic fluid used to stabilize bore holes during pile construction by maintaining hydrostatic pressure on walls.", "difficulty": "medium", "source": "Foundation Engineering \u2014 Pile Construction"},
        {"question": "Which type of foundation is most suitable for bridges over rivers with deep scour?", "options": ["Open foundation", "Well foundation", "Pile foundation", "Raft foundation"], "correct": 1, "explanation": "Well (caisson) foundations are most suitable for bridges over rivers with deep scour as they can be sunk to great depths below scour level.", "difficulty": "medium", "source": "IRBM \u2014 Foundation Types"},
        {"question": "The agency responsible for inspection of railway bridges (major) is ___", "options": ["ADEN", "SSE/Bridge", "Divisional Engineer", "Chief Bridge Engineer"], "correct": 2, "explanation": "Major bridge inspections are done by the Divisional Engineer as per the IRBM inspection schedule.", "difficulty": "easy", "source": "IRBM \u2014 Inspection Schedule"},
        {"question": "Lacey's regime theory is used for ___", "options": ["Design of bridge superstructure", "Calculation of scour depth", "Design of piers", "Calculation of bearing capacity"], "correct": 1, "explanation": "Lacey's regime theory is used to calculate the design scour depth (normal scour depth) at bridge foundations in alluvial rivers.", "difficulty": "medium", "source": "IRBM / Hydraulics \u2014 Scour Calculation"},
    ],
    "IRBM": [
        {"question": "As per IRBM, bridge inspection by SSE/Bridge should be done ___", "options": ["Once in 3 months", "Once in 6 months", "Once a year", "Once in 2 years"], "correct": 1, "explanation": "SSE/Bridge is required to inspect railway bridges once in every 6 months as per IRBM inspection schedule.", "difficulty": "easy", "source": "IRBM Chapter \u2014 Inspection Schedule"},
        {"question": "The minimum clearance between the highest flood level (HFL) and the underside of the lowest girder is ___", "options": ["300 mm", "450 mm", "600 mm", "900 mm"], "correct": 2, "explanation": "As per IRS bridge rules, a minimum clearance of 600 mm must be maintained between HFL and the underside of girder/soffit.", "difficulty": "medium", "source": "IRS Bridge Rules \u2014 Clearances"},
        {"question": "CRN stands for ___", "options": ["Condition Rating Number", "Current Repair Number", "Cumulative Record Number", "Component Rating Note"], "correct": 0, "explanation": "CRN (Condition Rating Number) is used in bridge inspection to rate the condition of each component from 0 (worst) to 6 (not applicable).", "difficulty": "easy", "source": "IRBM \u2014 Bridge Inspection System"},
        {"question": "The waterway of a bridge is designed based on ___", "options": ["Normal flood discharge", "Maximum observed flood discharge", "Design flood discharge", "Minimum dry season discharge"], "correct": 2, "explanation": "Bridge waterway is designed based on the design flood discharge, which accounts for the worst probable flood condition.", "difficulty": "medium", "source": "IRBM \u2014 Hydraulic Design"},
        {"question": "As per IRBM, the Schedule of Inspection of bridges by JE/SE is done ___", "options": ["Monthly", "Quarterly", "Half-yearly", "Annually"], "correct": 1, "explanation": "JE/SE level officers are required to inspect bridges quarterly (once every 3 months) as per IRBM Chapter on maintenance.", "difficulty": "easy", "source": "IRBM \u2014 Inspection by JE/SE"},
        {"question": "Which of the following is NOT a type of bridge foundation used in Indian Railways?", "options": ["Open foundation", "Well foundation", "Pile foundation", "Mat foundation"], "correct": 3, "explanation": "Mat (raft) foundations are not typically used for railway bridge piers. Open, well, and pile foundations are standard types used in Indian Railways.", "difficulty": "hard", "source": "IRBM \u2014 Foundation Types"},
        {"question": "The purpose of a bed block in bridge construction is ___", "options": ["To distribute the load from the girder to the substructure", "To prevent scour", "To hold the bearing in position", "To provide drainage"], "correct": 0, "explanation": "A bed block (bearing block) distributes the concentrated load from the girder bearing evenly across the top of the pier or abutment.", "difficulty": "medium", "source": "IRBM \u2014 Bridge Components"},
        {"question": "Flushing of arches and masonry bridges should be done ___", "options": ["Before every monsoon", "After every monsoon", "Both before and after monsoon", "Once in 2 years"], "correct": 2, "explanation": "Arch and masonry bridges should be inspected and flushed both before monsoon (preparation) and after monsoon (damage assessment).", "difficulty": "medium", "source": "IRBM \u2014 Maintenance Schedule"},
    ],
    "IRPWM": [
        {"question": "As per IRPWM, the standard size of sleeper for Broad Gauge (BG) track is ___", "options": ["2600 mm \u00d7 250 mm \u00d7 200 mm", "2750 mm \u00d7 250 mm \u00d7 210 mm", "2800 mm \u00d7 250 mm \u00d7 200 mm", "2600 mm \u00d7 200 mm \u00d7 150 mm"], "correct": 1, "explanation": "Standard BG concrete sleeper dimensions are 2750 mm (length) \u00d7 250 mm (width) \u00d7 210 mm (depth) as per IRPWM specifications.", "difficulty": "medium", "source": "IRPWM Para \u2014 Sleeper Standards"},
        {"question": "The schedule of inspection by ADEN for normal track is ___", "options": ["Once a month", "Once in 3 months", "Once in 6 months", "Once a year"], "correct": 3, "explanation": "ADEN is required to inspect normal track once a year (annually) as per IRPWM inspection schedule for permanent way officials.", "difficulty": "easy", "source": "IRPWM Para \u2014 Inspection Schedule"},
        {"question": "What is the normal gauge for Broad Gauge in Indian Railways?", "options": ["1435 mm", "1600 mm", "1676 mm", "1000 mm"], "correct": 2, "explanation": "The standard gauge for Broad Gauge in Indian Railways is 1676 mm (5 ft 6 inches), measured between inner faces of rail heads.", "difficulty": "easy", "source": "IRPWM Para 101 \u2014 Track Standards"},
        {"question": "As per IRPWM, the maximum permissible speed on a track with maximum unevenness is ___", "options": ["30 kmph", "45 kmph", "50 kmph", "75 kmph"], "correct": 0, "explanation": "When track geometry is severely deteriorated (maximum unevenness), speed must be restricted to 30 kmph as a safety measure.", "difficulty": "medium", "source": "IRPWM \u2014 Speed Restrictions"},
        {"question": "Fish plates are used to ___", "options": ["Connect two rail ends", "Connect rail to sleeper", "Provide drainage", "Prevent rail fracture"], "correct": 0, "explanation": "Fish plates (joint bars) are used to connect two rail ends at joints, maintaining alignment and gauge continuity.", "difficulty": "easy", "source": "IRPWM \u2014 Track Fixtures"},
        {"question": "Track patrolling in summer for speeds > 110 kmph route: push trolley or by foot inspection of entire section should be done ___", "options": ["Once in 2 months", "Once in 3 months", "Once in 4 months", "Once in 6 months"], "correct": 2, "explanation": "For speeds > 110 kmph, complete push trolley/foot inspection of the entire section must be done once in 4 months as per IRPWM.", "difficulty": "easy", "source": "IRPWM \u2014 Inspection Schedule ADEN"},
        {"question": "The minimum density of sleepers per km for BG main line track is ___", "options": ["1340 N/km", "1540 N/km", "1660 N/km", "1818 N/km"], "correct": 3, "explanation": "The minimum sleeper density for BG main line track is 1818 No./km (M+7 spacing) as per IRPWM specifications.", "difficulty": "hard", "source": "IRPWM \u2014 Sleeper Density"},
        {"question": "Creep of rails is caused by ___", "options": ["Expansion and contraction due to temperature", "Braking and traction forces", "Both temperature and braking/traction forces", "Excessive axle loads only"], "correct": 2, "explanation": "Rail creep occurs due to a combination of thermal expansion/contraction and braking/traction forces from passing trains.", "difficulty": "medium", "source": "IRPWM \u2014 Rail Maintenance"},
        {"question": "The purpose of providing cant (superelevation) in a curve is ___", "options": ["To increase speed", "To counteract centrifugal force on curves", "To reduce wear on rails", "To improve drainage"], "correct": 1, "explanation": "Superelevation (cant) on curves is provided to counteract the centrifugal force on vehicles, ensuring stable and comfortable travel.", "difficulty": "easy", "source": "IRPWM \u2014 Curves"},
        {"question": "LWR stands for ___", "options": ["Longitudinal Welded Rail", "Long Welded Rail", "Latest Welded Rail", "Lateral Welded Rail"], "correct": 1, "explanation": "LWR (Long Welded Rail) is rail welded into lengths greater than 250 m to reduce number of joints and improve ride quality.", "difficulty": "easy", "source": "IRPWM / SOD \u2014 LWR"},
        {"question": "As per IRPWM, the maximum cant deficiency permitted on BG for passenger trains is ___", "options": ["50 mm", "75 mm", "100 mm", "125 mm"], "correct": 1, "explanation": "The maximum permissible cant deficiency on BG track for passenger trains is 75 mm as per IRPWM curve standards.", "difficulty": "hard", "source": "IRPWM \u2014 Curve Standards"},
        {"question": "Track geometry parameters measured by MTRC (Mechanical Track Recording Car) include ___", "options": ["Only gauge and alignment", "Gauge, alignment, cross-level and unevenness", "Only unevenness and twist", "Gauge and sleeper spacing only"], "correct": 1, "explanation": "MTRC measures all key track geometry parameters: gauge, alignment, cross-level (cant), longitudinal unevenness, and twist.", "difficulty": "medium", "source": "IRPWM \u2014 Track Maintenance Machines"},
        {"question": "The minimum radius of curve permissible on BG main line in Indian Railways is ___", "options": ["175 m", "200 m", "175 m", "175 m"], "correct": 1, "explanation": "The absolute minimum radius of curve on BG main line is 175 m (special circumstances), while 200 m is the minimum for group A & B routes.", "difficulty": "hard", "source": "IRPWM \u2014 Curve Standards"},
        {"question": "Rails are classified by ___", "options": ["Their length", "Their weight per meter", "Their chemical composition", "Their manufacturing process"], "correct": 1, "explanation": "Rails are classified by their weight per running metre (e.g., 60 kg/m, 52 kg/m, 90 R) which indicates their cross-sectional properties.", "difficulty": "easy", "source": "IRPWM \u2014 Rail Standards"},
        {"question": "The purpose of ballast in a railway track is ___", "options": ["To provide a drainage path only", "To distribute load, maintain stability and provide drainage", "To anchor sleepers only", "To provide track elasticity only"], "correct": 1, "explanation": "Ballast performs multiple functions: distributes and spreads wheel loads, holds sleepers in position, provides drainage, and damps vibration.", "difficulty": "easy", "source": "IRPWM \u2014 Ballast"},
        {"question": "Flash butt welding of rails is done by ___", "options": ["SSE/PWay at site", "Central Welding Depot", "Mobile Flash Butt Welding Machine", "Either at depot or by mobile machine"], "correct": 3, "explanation": "Flash butt welding can be done either at a central welding depot (stationary machine) or by mobile flash butt welding machine at site.", "difficulty": "medium", "source": "IRPWM / SOD \u2014 Rail Welding"},
        {"question": "As per IRPWM, sleeper density is expressed as ___", "options": ["Number of sleepers per metre", "Number per km", "M + number (where M = 1000/sleeper spacing in mm)", "Weight per metre"], "correct": 2, "explanation": "Sleeper density is expressed as M+x, where M represents 1000 and x represents the number added. For example M+7 means 1000/(spacing in mm).", "difficulty": "hard", "source": "IRPWM \u2014 Sleeper Density Expression"},
        {"question": "The normal service life of 60 kg rail on BG main line is approximately ___", "options": ["10 years", "15 years", "20 years", "25 years"], "correct": 2, "explanation": "The normal service life of 60 kg/m rail on BG main line (group A routes) is approximately 20 years under normal traffic conditions.", "difficulty": "medium", "source": "IRPWM \u2014 Rail Renewal Program"},
        {"question": "As per IRPWM, the prescribed speed for inspection of track by motor trolley by SSE/P.Way is ___", "options": ["Not more than 30 kmph", "Not more than 20 kmph", "Not more than 25 kmph", "Not more than 15 kmph"], "correct": 0, "explanation": "Track inspection by motor trolley must be done at not more than 30 kmph to allow proper observation of track condition.", "difficulty": "medium", "source": "IRPWM \u2014 Track Inspection"},
        {"question": "Alumino Thermit (AT) welding is used for ___", "options": ["Primary welding of rails in depots", "Closure welds and repair welds at site", "Welding of turnouts only", "All types of rail welding"], "correct": 1, "explanation": "AT welding (Thermit welding) is primarily used for closure welds in LWR/CWR and for in-situ repair welds at site due to its portability.", "difficulty": "medium", "source": "IRPWM / SOD \u2014 AT Welding"},
        {"question": "The buffer rails in LWR (Long Welded Rail) are provided to ___", "options": ["Increase track strength", "Absorb thermal expansion and contraction at LWR ends", "Mark the end of welded rail", "Connect to crossing"], "correct": 1, "explanation": "Buffer rails (joggled fish plate zone) at LWR ends are provided to absorb the thermal movement that cannot be accommodated within the LWR breathing length.", "difficulty": "hard", "source": "IRPWM / LWR Manual"},
        {"question": "The maximum permissible temperature variation for laying LWR is ___", "options": ["\u00b15\u00b0C of stress free temperature", "\u00b110\u00b0C of stress free temperature", "\u00b115\u00b0C of stress free temperature", "\u00b120\u00b0C of stress free temperature"], "correct": 1, "explanation": "LWR should be laid/destressed within \u00b110\u00b0C of the stress free temperature (SFT) to prevent buckling or fracture.", "difficulty": "hard", "source": "IRPWM \u2014 LWR Maintenance"},
    ],
    "SOD_USFD": [
        {"question": "USFD test of rails is done to detect ___", "options": ["Surface cracks", "Internal/subsurface defects", "Rail wear", "Track geometry defects"], "correct": 1, "explanation": "USFD (Ultrasonic Flaw Detection) test is performed to detect internal defects like transverse fissures, horizontal split heads, and other subsurface flaws in rails.", "difficulty": "easy", "source": "SOD / USFD Manual"},
        {"question": "The frequency of USFD testing of rails on A & B routes (BG) is ___", "options": ["Every 6 months", "Annually", "Every 2 years", "Before and after monsoon"], "correct": 0, "explanation": "On A and B routes, USFD testing is done every 6 months (twice a year) due to heavy traffic to ensure early detection of rail defects.", "difficulty": "medium", "source": "USFD Manual \u2014 Testing Frequency"},
        {"question": "Schedule of Dimensions (SOD) gives ___", "options": ["The maintenance schedule for tracks", "The standard dimensions, clearances and tolerances for railway structures", "The dimensions of locomotives", "The timetable of trains"], "correct": 1, "explanation": "SOD (Schedule of Dimensions) is a reference document giving standard clearances, track centers, platform heights, structure gauges, and other dimensional standards for Indian Railways.", "difficulty": "easy", "source": "SOD \u2014 Introduction"},
        {"question": "The minimum clearance between two adjacent running lines (track centers) on BG main line is ___", "options": ["4.265 m", "5.0 m", "5.3 m", "3.5 m"], "correct": 0, "explanation": "The minimum track center distance for BG on straight main lines is 4.265 m (14 ft) as specified in Schedule of Dimensions.", "difficulty": "medium", "source": "SOD \u2014 Track Centers"},
        {"question": "As per SOD, the maximum height of platform for BG track is ___", "options": ["840 mm above rail level", "760 mm above rail level", "915 mm above rail level", "1000 mm above rail level"], "correct": 1, "explanation": "The maximum standard platform height for BG track is 760 mm above rail level (high level platform) as per SOD specifications.", "difficulty": "medium", "source": "SOD \u2014 Platform Dimensions"},
        {"question": "USFD testing uses which type of waves?", "options": ["X-rays", "Gamma rays", "Ultrasonic sound waves", "Infrared waves"], "correct": 2, "explanation": "USFD uses high-frequency sound waves (ultrasonic) to detect internal flaws by sending pulses through the rail and analyzing reflected echoes.", "difficulty": "easy", "source": "USFD Manual \u2014 Testing Method"},
    ],
    "IRWM": [
        {"question": "As per IRWM, the minimum slope of flat roof so that rain water gets drained off is ___", "options": ["1 in 30", "1 in 50", "1 in 60", "1 in 100"], "correct": 3, "explanation": "IRWM specifies the minimum slope for flat roofs as 1 in 100 to ensure effective drainage of rainwater.", "difficulty": "easy", "source": "IRWM \u2014 Building Standards"},
        {"question": "For design of sewage system as per IRWM, ___ of the water supplied is considered to reach sewers.", "options": ["90%", "80%", "75%", "70%"], "correct": 2, "explanation": "As per IRWM, 75% of the water supplied to a colony/station is assumed to reach the sewers for sewage system design.", "difficulty": "medium", "source": "IRWM \u2014 Sanitation Design"},
        {"question": "Floor of bathroom should be provided with a slope of minimum ___ towards outlet for effective draining.", "options": ["1 in 100", "1 in 40", "1 in 80", "1 in 60"], "correct": 0, "explanation": "As per IRWM building standards, bathroom floors should have a minimum slope of 1 in 100 towards the outlet for effective drainage.", "difficulty": "easy", "source": "IRWM \u2014 Building Standards"},
        {"question": "Periodicity of white washing kitchen of officers quarters is ___", "options": ["Once in a year", "Once in two years", "There is no periodicity", "Once in three years"], "correct": 2, "explanation": "White washing of kitchens in officers' quarters has no fixed periodicity under IRWM \u2014 it is done as required based on condition.", "difficulty": "medium", "source": "IRWM \u2014 Maintenance Schedule"},
        {"question": "As per IRWM, the amount of residual chlorine left in public water supply for safety against pathogenic bacteria is about ___", "options": ["0.2 mg/L", "0.6 mg/L", "0.8 mg/L", "1.0 to 5.0 ppm"], "correct": 0, "explanation": "The residual chlorine level maintained in public water supply systems as per IRWM/PHE standards is 0.2 mg/L (0.2 ppm) at consumer end.", "difficulty": "easy", "source": "IRWM \u2014 Water Supply"},
        {"question": "Land boundary verification certificate is submitted annually by ___", "options": ["SSE/Works", "SSE/P.Way", "ADEN", "SSE/Works or SSE/P.Way as the case may be"], "correct": 3, "explanation": "Land boundary verification certificate is submitted annually by the concerned SSE \u2014 either SSE/Works or SSE/P.Way depending on the jurisdiction.", "difficulty": "medium", "source": "IRWM \u2014 Land Records"},
        {"question": "As per IRWM, provision of septic tanks with soak pit/filter bed is NOT appropriate for toilets ___", "options": ["Of platform at small stations", "Of gate lodge quarters in mid-section", "Of colony in heavily built up urban areas", "All of the given options are correct"], "correct": 2, "explanation": "In heavily built-up urban areas, septic tanks with soak pits are not appropriate as land is limited and municipal sewage connections should be used instead.", "difficulty": "medium", "source": "IRWM \u2014 Sanitation Systems"},
        {"question": "Shear wall is a wall that is primarily designed to resist ___", "options": ["Vertical forces", "Lateral forces", "Bending moment", "All of these"], "correct": 1, "explanation": "Shear walls are structural walls designed to resist lateral (horizontal) forces such as wind loads and seismic forces in a building.", "difficulty": "easy", "source": "IRWM / Structural Engineering"},
        {"question": "The 'Right to Fair Compensation and Transparency in Land Acquisition, Rehabilitation and Resettlement Act 2013' is applicable for ___", "options": ["Land acquisition", "Land licensing", "Land purchase", "All of the given answers"], "correct": 0, "explanation": "The RFCTLARR Act 2013 specifically deals with land acquisition by government/public authorities, ensuring fair compensation to affected persons.", "difficulty": "easy", "source": "IRWM \u2014 Land Acquisition"},
        {"question": "As per IRWM, the minimum number of waterborne disease cases to declare an epidemic is ___", "options": ["5 cases", "10 cases", "Any number beyond normal", "20 cases"], "correct": 2, "explanation": "An epidemic is declared when the number of disease cases significantly exceeds the normal incidence in the area \u2014 there is no fixed minimum number.", "difficulty": "hard", "source": "IRWM \u2014 Public Health"},
        {"question": "Which of the following is the minimum number of WCs required per 25 males in a railway colony as per IRWM?", "options": ["1", "2", "3", "4"], "correct": 0, "explanation": "As per IRWM sanitation norms for railway colonies, a minimum of 1 WC per 25 males is prescribed.", "difficulty": "hard", "source": "IRWM \u2014 Sanitation Norms"},
        {"question": "As per IRWM, the design period for water supply schemes is ___", "options": ["10 years", "20 years", "25 years", "30 years"], "correct": 1, "explanation": "Water supply schemes for railway colonies/stations are designed for a period of 20 years to ensure adequate capacity for future growth.", "difficulty": "medium", "source": "IRWM \u2014 Water Supply Design"},
    ],
    "TrackMachines": [
        {"question": "Duomatic machine is used for ___", "options": ["Rail grinding", "Track tamping and lining", "Ballast cleaning", "Sleeper renewal"], "correct": 1, "explanation": "Duomatic is a continuous action tamping and lining machine (CATL) used for tamping (packing ballast under sleepers) and lateral alignment correction.", "difficulty": "easy", "source": "IRPWM \u2014 Track Machines"},
        {"question": "BCM (Ballast Cleaning Machine) is used to ___", "options": ["Lay new ballast", "Clean and screen the existing dirty ballast", "Compact the ballast", "Measure ballast depth"], "correct": 1, "explanation": "BCM excavates the existing fouled ballast, screens/cleans it by removing fines and dirt, and returns cleaned ballast to the track.", "difficulty": "easy", "source": "IRPWM \u2014 Track Machines"},
        {"question": "DTS (Dynamic Track Stabilizer) is used after tamping to ___", "options": ["Increase train speed immediately after tamping", "Consolidate ballast and achieve geometric stability quickly", "Clean the ballast", "Level the track"], "correct": 1, "explanation": "DTS applies controlled vibration and vertical load to the track after tamping to accelerate ballast consolidation and achieve early geometric stability.", "difficulty": "medium", "source": "IRPWM \u2014 Track Machines"},
        {"question": "The speed restriction imposed after tamping by UNIMAT/Duomatic machine on BG is ___", "options": ["No restriction", "30 kmph for 3 months", "Engineering speed (30 kmph) until consolidation", "50 kmph for first 3 days"], "correct": 2, "explanation": "After tamping, a speed restriction of 30 kmph (engineering speed) is imposed until the track geometry consolidates sufficiently under traffic.", "difficulty": "medium", "source": "IRPWM \u2014 Post-Tamping Speed"},
        {"question": "FRM (Flashbutt Rail welding Machine) works on the principle of ___", "options": ["Alumino thermit reaction", "Electrical resistance and pressure", "Gas welding", "Arc welding"], "correct": 1, "explanation": "Flash butt welding works by passing heavy electric current through rail ends (resistance heating) until they reach welding temperature, then pressing them together.", "difficulty": "medium", "source": "SOD \u2014 Rail Welding Machines"},
        {"question": "PQRS machine is used for ___", "options": ["Quality testing of rails", "Rail profile measurement", "Rail grinding", "Track geometry recording"], "correct": 2, "explanation": "PQRS (Profile Quality Rail Surface) machine is a rail grinding machine used to restore the correct rail head profile and remove corrugation.", "difficulty": "medium", "source": "IRPWM \u2014 Track Machines"},
        {"question": "TRT (Tie Replacement Train) is used for ___", "options": ["Laying new track", "Replacing individual sleepers without disturbing track geometry much", "Tamping", "Ballast cleaning"], "correct": 1, "explanation": "TRT is a mechanized sleeper replacement machine that removes old sleepers and inserts new ones continuously without removing ballast.", "difficulty": "hard", "source": "IRPWM \u2014 Track Machines"},
        {"question": "Ballast Regulator (BR) is used to ___", "options": ["Measure ballast depth", "Distribute and profile ballast along the track", "Compact ballast", "Clean dirty ballast"], "correct": 1, "explanation": "Ballast Regulator spreads, distributes and profiles ballast along the track, forming the correct cross-section after tamping or ballast delivery.", "difficulty": "easy", "source": "IRPWM \u2014 Track Machines"},
    ],
    "Establishment": [
        {"question": "The appointing authority for Group C railway employees is ___", "options": ["Railway Board", "General Manager", "Divisional Railway Manager", "Senior Divisional Personnel Officer"], "correct": 3, "explanation": "For Group C (erstwhile Group D promoted to C) railway employees, the appointing authority is the Senior Divisional Personnel Officer (Sr.DPO) at divisional level.", "difficulty": "medium", "source": "Railway Establishment Manual \u2014 Appointment"},
        {"question": "Annual Confidential Report (ACR) of a Railway employee is written by ___", "options": ["Himself/herself", "Immediate superior officer", "Personnel department", "Divisional Manager"], "correct": 1, "explanation": "ACR/APAR (Annual Performance Appraisal Report) is written by the immediate superior officer who is in the best position to assess daily performance.", "difficulty": "easy", "source": "Railway Establishment \u2014 Service Records"},
        {"question": "The maximum age limit for direct recruitment to Group C posts in Indian Railways is ___", "options": ["25 years", "30 years", "35 years", "Age varies by post"], "correct": 3, "explanation": "The upper age limit varies by post \u2014 typically 18-33 years for most Group C posts, with relaxations for SC/ST (5 years) and OBC (3 years).", "difficulty": "medium", "source": "Railway Establishment \u2014 Recruitment Rules"},
        {"question": "Earned Leave (EL) is credited at the rate of ___ days per year for railway employees.", "options": ["15 days", "20 days", "30 days", "12 days"], "correct": 2, "explanation": "Earned Leave is credited at 30 days per year (2.5 days per month) to railway employees under the Leave Rules.", "difficulty": "easy", "source": "Railway Leave Rules"},
        {"question": "Half Pay Leave (HPL) is credited at the rate of ___ days per year.", "options": ["10 days", "15 days", "20 days", "30 days"], "correct": 1, "explanation": "Half Pay Leave is credited at 20 days per year (10 days per half year) to railway employees under the Leave Rules.", "difficulty": "easy", "source": "Railway Leave Rules"},
        {"question": "The period for which Leave Not Due (LND) can be granted is limited to ___", "options": ["90 days during entire service", "180 days during entire service", "360 days during entire service", "60 days at a time"], "correct": 1, "explanation": "Leave Not Due can be granted for a maximum of 360 days during entire service, but not more than 180 days at one time.", "difficulty": "hard", "source": "Railway Leave Rules \u2014 LND"},
        {"question": "Commuted Leave can be taken as ___", "options": ["Double the HPL on medical certificate", "Half the EL balance", "Full HPL balance", "Leave encashment"], "correct": 0, "explanation": "Commuted Leave is granted as double the Half Pay Leave (HPL) balance on medical certificate, where HPL is debited half the commuted period.", "difficulty": "medium", "source": "Railway Leave Rules \u2014 Commuted Leave"},
        {"question": "The minimum service required for eligibility for Voluntary Retirement Scheme (VRS) in Indian Railways is ___", "options": ["10 years", "15 years", "20 years", "25 years"], "correct": 2, "explanation": "An employee is eligible for VRS (Voluntary Retirement) after completing 20 years of qualifying service as per CCS Pension Rules.", "difficulty": "medium", "source": "Railway Establishment \u2014 Retirement Rules"},
        {"question": "Leave Encashment on retirement: maximum number of EL days that can be encashed is ___", "options": ["150 days", "240 days", "300 days", "365 days"], "correct": 1, "explanation": "A maximum of 300 days of Earned Leave can be encashed at the time of retirement (including superannuation, VRS, and death cases).", "difficulty": "medium", "source": "Railway Leave Rules \u2014 Leave Encashment"},
        {"question": "A railway employee placed under suspension receives ___", "options": ["Full pay and allowances", "No pay", "Subsistence allowance (usually 50% of basic pay)", "Half pay leave salary"], "correct": 2, "explanation": "During suspension, an employee receives a subsistence allowance \u2014 typically 50% of basic pay for first 90 days, which may be revised thereafter.", "difficulty": "medium", "source": "Railway Establishment \u2014 Suspension"},
        {"question": "Which of the following is a Minor Penalty under Railway Servants (Discipline and Appeal) Rules?", "options": ["Compulsory retirement", "Reduction in pay", "Censure", "Removal from service"], "correct": 2, "explanation": "Censure (written warning/reprimand) is a minor penalty. Major penalties include reduction in rank/pay, compulsory retirement, removal and dismissal.", "difficulty": "easy", "source": "Railway D&A Rules \u2014 Penalties"},
        {"question": "The appeal against an order imposing major penalty on a Group C employee lies with ___", "options": ["General Manager", "Divisional Railway Manager", "Railway Board", "Senior Personnel Officer"], "correct": 0, "explanation": "For Group C employees, appeal against major penalty orders lies with the General Manager of the Zonal Railway.", "difficulty": "medium", "source": "Railway D&A Rules \u2014 Appeals"},
        {"question": "Gratuity under Retirement Gratuity scheme is calculated as ___", "options": ["One month's pay per year of service", "Quarter month's pay per 6 months of qualifying service, max 16.5 times", "Half month's pay per year", "Full month's pay for first 5 years"], "correct": 1, "explanation": "Retirement Gratuity = (Basic Pay + DA) \u00d7 1/4 per 6 months of qualifying service, subject to maximum of 16.5 months' pay.", "difficulty": "hard", "source": "Railway Establishment \u2014 Pension Rules"},
        {"question": "DA (Dearness Allowance) is revised by Government ___", "options": ["Every month", "Quarterly", "Twice a year (on 1 January and 1 July)", "Once a year"], "correct": 2, "explanation": "DA is revised twice a year \u2014 effective from 1st January and 1st July \u2014 based on CPI (Industrial Workers) index to compensate for inflation.", "difficulty": "easy", "source": "Railway Pay Rules \u2014 DA"},
        {"question": "Casual Leave (CL) entitlement per year for a railway employee is ___", "options": ["6 days", "8 days", "10 days", "12 days"], "correct": 2, "explanation": "Railway employees are entitled to 8 days of Casual Leave per calendar year (not encashable, not carried forward).", "difficulty": "easy", "source": "Railway Leave Rules \u2014 CL"},
    ],
    "Finance_Stores": [
        {"question": "The purpose of a Budget is ___", "options": ["To spend maximum funds", "An estimate of receipts and expenditures for the coming year, duly authorized", "A statement of past expenditure", "A plan for infrastructure creation"], "correct": 1, "explanation": "Budget is the annual financial statement presenting estimated receipts and expenditures for the coming financial year, approved by Parliament/authority.", "difficulty": "easy", "source": "Railway Finance Manual \u2014 Budget"},
        {"question": "As per Indian Railways financial rules, the financial year is from ___", "options": ["January to December", "April to March", "July to June", "October to September"], "correct": 1, "explanation": "The Indian Government/Railways financial year runs from 1st April to 31st March of the next calendar year.", "difficulty": "easy", "source": "Railway Finance \u2014 Financial Year"},
        {"question": "Imprest Cash is maintained for ___", "options": ["Major capital purchases", "Small and urgent petty cash expenditures", "Salary payments", "Advances to contractors"], "correct": 1, "explanation": "Imprest Cash (Petty Cash) is a small fixed amount given to officials to meet urgent, small day-to-day expenses without going through regular bill procedure.", "difficulty": "easy", "source": "Railway Finance Manual \u2014 Imprest Cash"},
        {"question": "The competent authority for sanction of works costing up to \u20b910 crore in Indian Railways is ___", "options": ["Section Engineer", "Divisional Railway Manager", "General Manager", "Railway Board"], "correct": 1, "explanation": "Divisional Railway Manager (DRM) has financial powers to sanction works up to certain limits; for \u20b910 crore level works, it typically falls within DRM/PHOD powers.", "difficulty": "medium", "source": "Railway Finance \u2014 Financial Powers"},
        {"question": "Tenders are invited for procurement of stores worth more than ___", "options": ["\u20b91 lakh", "\u20b92 lakhs", "\u20b95 lakhs", "\u20b925,000"], "correct": 1, "explanation": "As per DGS&D/Railway procurement norms, open/limited tenders are invited for purchases above \u20b92 lakhs; below this, purchases may be made through limited quotations.", "difficulty": "medium", "source": "Railway Stores Manual \u2014 Tender Limits"},
        {"question": "Stock verification in railways is done by ___", "options": ["Store keeper himself", "Finance Inspector", "Accounts Department", "External Auditors only"], "correct": 1, "explanation": "Physical stock verification in railway stores depots is conducted by Finance Inspectors (from accounts/finance wing) to ensure accuracy of stock records.", "difficulty": "medium", "source": "Railway Stores Manual \u2014 Stock Verification"},
        {"question": "The document authorizing release of material from railway stores is called ___", "options": ["Indent", "Material Received Note", "Issue Note / Voucher", "Delivery Note"], "correct": 2, "explanation": "An Issue Note (also called Issue Voucher or Material Issue Note) is the document that authorizes release of materials from the stores to the requisitioning authority.", "difficulty": "easy", "source": "Railway Stores Manual \u2014 Issue Procedure"},
        {"question": "BG (Budget Grant) in railway finance refers to ___", "options": ["Budget Guarantee", "Budgetary Grant approved by Parliament for specific heads of expenditure", "Bank Guarantee from contractors", "Building Grant"], "correct": 1, "explanation": "Budgetary Grant (BG) is the amount approved by Parliament under various heads of account that authorizes expenditure up to that limit.", "difficulty": "medium", "source": "Railway Finance \u2014 Budget Grants"},
        {"question": "Advance Correction Slip (ACS) is issued to ___", "options": ["Correct errors in pay bills", "Update and amend railway codes and manuals", "Advance payment to contractors", "Correct store accounts"], "correct": 1, "explanation": "ACS (Advance Correction Slip) is issued to make advance amendments to railway codes, manuals and schedules before they are formally revised.", "difficulty": "easy", "source": "Railway Administration \u2014 Codes"},
        {"question": "Dead Stock in railway stores refers to ___", "options": ["Stock that has expired", "Items that are non-consumable (furniture, equipment, machinery)", "Stock written off", "Slow-moving stock"], "correct": 1, "explanation": "Dead Stock refers to non-consumable, durable items like furniture, equipment, machinery, and tools that are used repeatedly and not consumed in one use.", "difficulty": "medium", "source": "Railway Stores Manual \u2014 Stock Classification"},
        {"question": "The EMD (Earnest Money Deposit) for tenders in Indian Railways is generally ___", "options": ["1% of estimated cost", "2% of estimated cost", "5% of estimated cost", "10% of estimated cost"], "correct": 1, "explanation": "EMD (Earnest Money Deposit) is typically 2% of the estimated cost of the contract, submitted with the tender to ensure seriousness of the bidder.", "difficulty": "medium", "source": "Railway Finance \u2014 Tender Conditions"},
        {"question": "Security Deposit from contractors in Indian Railways is ___", "options": ["2% of contract value", "5% of contract value", "10% of contract value", "2.5% of contract value"], "correct": 2, "explanation": "Security Deposit (SD) from contractors is deducted at 10% of the gross bill amount (or 5% upfront + 5% deducted) to ensure performance of the contract.", "difficulty": "medium", "source": "Railway Finance \u2014 Contract Management"},
        {"question": "Scrap materials in railway stores are disposed by ___", "options": ["Direct sale to public", "Auction or tender method", "Transfer to other railways only", "Writing off without sale"], "correct": 1, "explanation": "Scrap and unserviceable materials are disposed of through public auction or open tender to get the best market price.", "difficulty": "easy", "source": "Railway Stores Manual \u2014 Scrap Disposal"},
        {"question": "The ceiling on cash purchase by a JE/AEN without tender formalities is ___", "options": ["\u20b95,000", "\u20b910,000", "\u20b915,000", "\u20b925,000"], "correct": 1, "explanation": "As per delegation of financial powers, a JE/AEN level officer can make spot/cash purchases up to \u20b910,000 without tender formalities for urgent requirements.", "difficulty": "medium", "source": "Railway Finance \u2014 Delegated Powers"},
        {"question": "Pensionary benefits in Indian Railways are regulated by ___", "options": ["Railway Act 1989", "Railway Services (Pension) Rules 1993", "Railway Establishment Manual", "CCS (Pension) Rules 1972"], "correct": 1, "explanation": "Pension for railway employees is governed by Railway Services (Pension) Rules 1993, which is specific to railway servants.", "difficulty": "easy", "source": "Railway Pension Rules"},
    ],
    "GeneralKnowledge": [
        {"question": "The total route length of Indian Railways (approx.) is ___", "options": ["45,000 km", "68,000 km", "72,000 km", "90,000 km"], "correct": 1, "explanation": "Indian Railways has a total route length of approximately 68,000 km, making it one of the largest rail networks in the world.", "difficulty": "easy", "source": "General Knowledge \u2014 Indian Railways"},
        {"question": "Indian Railways was nationalised in ___", "options": ["1947", "1951", "1953", "1950"], "correct": 2, "explanation": "All the various private and state railway companies were nationalised and merged into a single entity \u2014 Indian Railways \u2014 in 1951-1953.", "difficulty": "medium", "source": "General Knowledge \u2014 Railway History"},
        {"question": "The highest railway station in India is ___", "options": ["Shimla", "Ghum (Darjeeling Himalayan Railway)", "Leh", "Siliguri"], "correct": 1, "explanation": "Ghum (also spelt Ghoom) station on the Darjeeling Himalayan Railway at 2,258 m above sea level is the highest railway station in India.", "difficulty": "medium", "source": "General Knowledge \u2014 Indian Railways"},
        {"question": "DFC (Dedicated Freight Corridor) in India is being implemented by ___", "options": ["Indian Railways directly", "DFCCIL (Dedicated Freight Corridor Corporation of India Ltd.)", "IRCON", "RITES"], "correct": 1, "explanation": "DFCCIL (Dedicated Freight Corridor Corporation of India Limited) is the special purpose vehicle set up by the Government of India to implement the DFC project.", "difficulty": "medium", "source": "General Knowledge \u2014 Railway Organizations"},
        {"question": "RITES stands for ___", "options": ["Rail India Technical and Economic Service", "Railway Infrastructure and Technical Engineering Service", "Rail India Transport and Economic Systems", "Railway International Technical Export Service"], "correct": 0, "explanation": "RITES (Rail India Technical and Economic Service) is a PSU under the Ministry of Railways providing transport infrastructure consulting and project management.", "difficulty": "easy", "source": "General Knowledge \u2014 Railway PSUs"},
        {"question": "The first railway in India ran between ___", "options": ["Delhi and Agra", "Mumbai (Bombay) and Thane", "Kolkata and Howrah", "Chennai (Madras) and Arcot"], "correct": 1, "explanation": "The first passenger train in India ran between Bori Bunder (Mumbai) and Thane on 16th April 1853, covering 34 km.", "difficulty": "easy", "source": "General Knowledge \u2014 Railway History"},
        {"question": "The zonal headquarters of South Central Railway is ___", "options": ["Chennai", "Hyderabad", "Secunderabad", "Bengaluru"], "correct": 2, "explanation": "South Central Railway (SCR) has its zonal headquarters at Secunderabad (Hyderabad).", "difficulty": "easy", "source": "General Knowledge \u2014 Railway Zones"},
        {"question": "The Railway Protection Force (RPF) is under the administrative control of ___", "options": ["Ministry of Home Affairs", "Ministry of Railways", "State Police", "Central Reserve Police Force"], "correct": 1, "explanation": "RPF (Railway Protection Force) is a security force established under the Railways Act and is under the administrative control of the Ministry of Railways.", "difficulty": "easy", "source": "General Knowledge \u2014 Railway Administration"},
        {"question": "Konkan Railway connects ___", "options": ["Delhi to Mumbai", "Mangaluru to Mumbai (Roha)", "Goa to Chennai", "Pune to Goa"], "correct": 1, "explanation": "Konkan Railway connects Roha (Maharashtra) to Mangaluru (Karnataka) along the western coast, covering approximately 741 km.", "difficulty": "medium", "source": "General Knowledge \u2014 Railway Projects"},
        {"question": "The first metro rail in India was commissioned in ___", "options": ["Mumbai", "Delhi", "Kolkata", "Chennai"], "correct": 2, "explanation": "Kolkata Metro was the first metro rail system in India, inaugurated in 1984 between Dumdum and Belgachia stations.", "difficulty": "easy", "source": "General Knowledge \u2014 Metro Rail"},
    ],
    "Hindi_Rajbhasha": [
        {"question": "The target fixed in Annual Programme for giving answer in Hindi for the letters received in Hindi is ___", "options": ["60%", "75%", "90%", "100%"], "correct": 3, "explanation": "As per Official Language Policy, replies to letters received in Hindi must be sent in Hindi \u2014 the target is 100%.", "difficulty": "easy", "source": "Rajbhasha Policy \u2014 Correspondence"},
        {"question": "Which Ministry issues important policy decisions pertaining to Official Language?", "options": ["Ministry of Home Affairs", "Ministry of Personnel", "Ministry of Education", "Ministry of Culture"], "correct": 0, "explanation": "The Department of Official Language under the Ministry of Home Affairs issues policy decisions, circulars and instructions on Official Language matters.", "difficulty": "easy", "source": "Official Language Policy"},
        {"question": "Official Languages Rules were framed in year ___", "options": ["1963", "1976", "1950", "1975"], "correct": 1, "explanation": "The Official Languages Rules were framed in 1976 under the Official Languages Act 1963 to give effect to the Act's provisions.", "difficulty": "easy", "source": "Official Language Rules 1976"},
        {"question": "As per the Constitution of India, the form of numerals to be used for official purposes of the Union shall be ___", "options": ["Devnagari form of Indian numerals", "International form of Indian numerals", "Indo-arabic form of Roman numerals", "Indian form of Roman numerals"], "correct": 1, "explanation": "Article 343 of the Constitution specifies that International form of Indian numerals (1,2,3...) shall be used for official purposes of the Union.", "difficulty": "medium", "source": "Constitution of India \u2014 Article 343"},
        {"question": "Who works as the Chairman of Central Hindi Committee?", "options": ["President of India", "Prime Minister of India", "Home Minister of India", "Chairman of the Parliamentary committee on Rajbhasha"], "correct": 1, "explanation": "The Central Hindi Committee (Kendriya Hindi Samiti) is chaired by the Prime Minister of India.", "difficulty": "medium", "source": "Official Language Committees"},
        {"question": "The award given for writing original books in Hindi on technical Railway subjects is ___", "options": ["Lal Bahadur Shastri Technical Puraskar", "Visvesvaraya Technical Puraskar", "Jagjivan Ram Technical Puraskar", "Rajeev Gandhi Technical Puraskar"], "correct": 0, "explanation": "Lal Bahadur Shastri Technical Puraskar is awarded by Indian Railways to employees who write original technical books in Hindi on railway subjects.", "difficulty": "medium", "source": "Railway Hindi Awards"},
        {"question": "Which of the following is NOT an incentive given to Railway employees for passing Hindi examinations?", "options": ["Cash award", "Lump sum award", "Personal pay", "Out of turn promotion"], "correct": 3, "explanation": "Out-of-turn promotion is NOT given for passing Hindi exams. Cash awards, lump sum awards, and personal pay are the incentives provided.", "difficulty": "medium", "source": "Railway Hindi Incentives"},
        {"question": "When did section 3(3) of the Official Language Act take effect?", "options": ["26 January 1950", "26 January 1965", "14 September 1956", "14 September 1950"], "correct": 1, "explanation": "Section 3(3) of the Official Language Act 1963 (mandating bilingual issue of documents like orders, notices, etc.) took effect from 26 January 1965.", "difficulty": "medium", "source": "Official Language Act 1963"},
        {"question": "How many sub-committees are there in the Parliamentary Committee on Official Language?", "options": ["3", "4", "2", "5"], "correct": 1, "explanation": "The Parliamentary Committee on Official Language has 4 sub-committees to examine different aspects of Hindi implementation.", "difficulty": "hard", "source": "Parliamentary Committee on Official Language"},
        {"question": "Who is the Chairman of the Official Language Implementation Committee of the Divisional Railway Office?", "options": ["Senior Divisional Personnel Officer", "Additional Divisional Railway Manager", "Divisional Railway Manager", "None of these"], "correct": 2, "explanation": "The Divisional Railway Manager (DRM) is the Chairman of the Official Language Implementation Committee at the Divisional level.", "difficulty": "medium", "source": "Railway Rajbhasha Committees"},
        {"question": "When was Sindhi language added to the Eighth Schedule of the Constitution?", "options": ["1967", "1976", "2004", "None of these"], "correct": 0, "explanation": "Sindhi language was added to the Eighth Schedule of the Indian Constitution by the 21st Constitutional Amendment in 1967.", "difficulty": "medium", "source": "Constitution \u2014 8th Schedule"},
        {"question": "The foreign language that is included in the 8th Schedule of the Constitution of India is ___", "options": ["Pashto", "Sinhala", "Dzongkha", "Nepali"], "correct": 3, "explanation": "Nepali language is listed in the Eighth Schedule of the Constitution. While Nepali is spoken across borders, it is recognized as a language of Indian communities in Sikkim and northeastern India.", "difficulty": "hard", "source": "Constitution \u2014 8th Schedule"},
        {"question": "Who was the first Chairman of the committee formed on the recommendation of the Official Language Commission?", "options": ["Maithili Sharan Gupt Puraskar", "Lal Bahadur Shastri", "Prem Chand Puraskar", "Govind Ballabh Pant"], "correct": 3, "explanation": "Govind Ballabh Pant was the first chairman of the committee formed on the recommendation of the Official Language Commission.", "difficulty": "hard", "source": "Official Language Commission"},
        {"question": "The name of the award given for writing Hindi poetry books is ___", "options": ["Prem Chand Puraskar", "Lal Bahadur Shastri Puraskar", "Visvesvaraya Puraskar", "Mahavir Prasad Dwivedi Puraskar"], "correct": 0, "explanation": "Prem Chand Puraskar is awarded for writing original Hindi poetry/literature books, named after the famous Hindi writer Munshi Premchand.", "difficulty": "medium", "source": "Hindi Literary Awards"},
        {"question": "How many languages were included in the Eighth Schedule of the Constitution when it was adopted?", "options": ["13", "14", "15", "16?"], "correct": 1, "explanation": "At the time the Indian Constitution was adopted in 1950, 14 languages were listed in the Eighth Schedule. Currently there are 22 scheduled languages.", "difficulty": "medium", "source": "Constitution \u2014 8th Schedule"},
    ],
    "Surveying": [
        {"question": "The principle of surveying is ___", "options": ["To work from part to whole", "To work from whole to part", "To work from temporary benchmark", "To work from any convenient starting point"], "correct": 1, "explanation": "The fundamental principle of surveying is to work from whole to part \u2014 establish overall control first, then fill in details. This minimizes accumulation of errors.", "difficulty": "easy", "source": "Surveying \u2014 Basic Principles"},
        {"question": "The instrument used for measuring horizontal and vertical angles in surveying is ___", "options": ["Level", "Theodolite", "Auto level", "Total Station"], "correct": 1, "explanation": "A Theodolite measures both horizontal angles (for bearing) and vertical angles (for elevation/depression), making it the primary angular measurement instrument.", "difficulty": "easy", "source": "Surveying \u2014 Instruments"},
        {"question": "Fly levelling is done ___", "options": ["For precise levelling of important structures", "To carry levels quickly over long distances between two points", "For contour survey", "For setting out curves"], "correct": 1, "explanation": "Fly levelling rapidly carries levels from one benchmark to another over long distances. Accuracy is less than precise levelling but speed is high.", "difficulty": "easy", "source": "Surveying \u2014 Levelling"},
        {"question": "GPS in surveying stands for ___", "options": ["Ground Positioning System", "Global Positioning System", "Geodetic Precision Survey", "Geographic Plot System"], "correct": 1, "explanation": "GPS (Global Positioning System) uses satellite signals to determine precise three-dimensional coordinates of any point on earth's surface.", "difficulty": "easy", "source": "Surveying \u2014 Modern Instruments"},
        {"question": "The formula for length of a circular curve is ___", "options": ["L = \u03c0R\u0394/180", "L = 2\u03c0R", "L = R tan(\u0394/2)", "L = 2R sin(\u0394/2)"], "correct": 0, "explanation": "Length of circular curve L = (\u03c0R\u0394)/180, where R = radius in meters and \u0394 = deflection angle in degrees. This converts arc angle to arc length.", "difficulty": "medium", "source": "Surveying \u2014 Curves"},
        {"question": "Ranging in chain surveying is done to ___", "options": ["Measure horizontal distances", "Establish intermediate points on a survey line between two endpoints", "Set out curves", "Measure offsets"], "correct": 1, "explanation": "Ranging establishes a series of intermediate ranging rods in a straight line between two survey stations, allowing accurate measurement along the survey line.", "difficulty": "easy", "source": "Surveying \u2014 Chain Surveying"},
        {"question": "The instrument used for measuring horizontal and vertical angles in surveying:", "options": ["Level", "Theodolite", "Plane table", "Alidade"], "correct": 1, "explanation": "Theodolite measures horizontal angles, vertical angles, deflection angles, magnetic bearings \u2014 primary angular measurement instrument.", "difficulty": "easy", "source": "Surveying & Levelling"},
        {"question": "In levelling, the Height of Instrument (HI) is calculated as:", "options": ["HI = RL \u2212 BS", "HI = RL + BS", "HI = RL \u2212 FS", "HI = FS \u2212 BS"], "correct": 1, "explanation": "Height of Instrument HI = RL of benchmark + Back Sight reading (BS).", "difficulty": "easy", "source": "Surveying \u2014 Levelling"},
        {"question": "The arithmetic check in levelling is:", "options": ["\u03a3BS \u2212 \u03a3FS = Last RL \u2212 First RL", "\u03a3BS + \u03a3FS = Last RL", "\u03a3BS = \u03a3FS", "\u03a3IS = \u03a3BS \u2212 \u03a3FS"], "correct": 0, "explanation": "Arithmetic check: \u03a3BS \u2212 \u03a3FS = Last RL \u2212 First RL (also \u03a3BS \u2212 \u03a3FS = \u03a3Rise \u2212 \u03a3Fall).", "difficulty": "medium", "source": "Surveying \u2014 Levelling"},
        {"question": "In chain surveying, the 'Base Line' is defined as:", "options": ["Shortest line of survey", "Longest line running through middle of area", "Line joining two stations", "Subsidiary line from main line"], "correct": 1, "explanation": "Base Line: the longest and most prominent chain line running through the middle of the survey area.", "difficulty": "easy", "source": "Surveying \u2014 Chain Survey"},
    ],
    "SOM": [
        {"question": "The stress-strain curve for a mild steel specimen shows ___", "options": ["No definite yield point", "A well-defined yield point and upper/lower yield points", "Continuous gradual increase without yield", "Brittle fracture without plastic deformation"], "correct": 1, "explanation": "Mild steel shows a characteristic stress-strain curve with a well-defined upper and lower yield point, followed by plastic deformation and strain hardening.", "difficulty": "easy", "source": "Strength of Materials \u2014 Stress-Strain"},
        {"question": "Young's Modulus of Elasticity (E) for structural steel is approximately ___", "options": ["100 GPa", "200 GPa", "210 GPa", "250 GPa"], "correct": 2, "explanation": "Young's Modulus of elasticity for structural steel is approximately 200-210 GPa (2\u00d710\u2075 MPa), used in structural calculations.", "difficulty": "easy", "source": "Strength of Materials \u2014 Elastic Constants"},
        {"question": "A simply supported beam with UDL (uniformly distributed load) of w per unit length and span L has maximum bending moment at ___", "options": ["Support ends", "Quarter span", "Mid-span (wL\u00b2/8)", "Third span"], "correct": 2, "explanation": "For a simply supported beam with UDL, maximum BM occurs at mid-span = wL\u00b2/8. At supports the BM is zero.", "difficulty": "easy", "source": "Strength of Materials \u2014 Beams"},
        {"question": "Factor of Safety (FOS) is defined as ___", "options": ["Working load / Ultimate load", "Ultimate stress / Permissible (working) stress", "Yield strength / Ultimate strength", "None of these"], "correct": 1, "explanation": "FOS = Ultimate stress / Permissible stress. It represents the ratio of the material's maximum capacity to the actual working stress.", "difficulty": "easy", "source": "Strength of Materials \u2014 Design Philosophy"},
        {"question": "Which of the following is a statically indeterminate structure?", "options": ["Simply supported beam", "Cantilever beam", "Continuous beam over 3 supports", "Free standing column"], "correct": 2, "explanation": "A continuous beam over 3 or more supports is statically indeterminate as the number of unknowns exceeds the available equilibrium equations.", "difficulty": "medium", "source": "Strength of Materials \u2014 Structural Analysis"},
        {"question": "How do short columns primarily fail?", "options": ["Buckling", "Tension", "Shear", "Direct crushing stress"], "correct": 3, "explanation": "Short columns fail due to direct compressive (crushing) stress when the material's ultimate compressive strength is exceeded, without significant buckling.", "difficulty": "easy", "source": "SOM \u2014 Column Theory"},
        {"question": "A structural member subjected to axial compressive force in any orientation is called:", "options": ["Beam", "Column", "Tie", "Strut"], "correct": 3, "explanation": "A strut is a compression member in any orientation; a column is specifically vertical.", "difficulty": "easy", "source": "SOM \u2014 Structural Members"},
        {"question": "The rate of change of Shear Force along a beam section equals:", "options": ["Bending Moment", "Load intensity at that section", "Deflection", "Slope of the beam"], "correct": 1, "explanation": "As per basic beam theory dV/dx = w (load intensity). The rate of change of SF equals the load intensity at that section.", "difficulty": "easy", "source": "SOM \u2014 Beam Theory"},
        {"question": "The rate of change of Bending Moment along a beam equals:", "options": ["Load intensity", "Deflection", "Shear force at that section", "Slope of elastic curve"], "correct": 2, "explanation": "The fundamental differential equation dM/dx = V states rate of change of BM equals shear force.", "difficulty": "easy", "source": "SOM \u2014 Beam Theory"},
        {"question": "Shape of Shear Force Diagram for a beam under UDL:", "options": ["Horizontal straight line", "Parabolic curve", "Inclined straight line", "Cubic curve"], "correct": 2, "explanation": "For UDL the shear force varies linearly, resulting in an inclined straight line SFD.", "difficulty": "easy", "source": "SOM \u2014 SFD/BMD"},
        {"question": "Shape of Shear Force Diagram for a beam under UVL (Uniformly Varying Load):", "options": ["Inclined straight line", "Parabolic curve", "Horizontal line", "Cubic curve"], "correct": 1, "explanation": "For UVL load intensity varies linearly, causing the SFD to be parabolic.", "difficulty": "medium", "source": "SOM \u2014 SFD/BMD"},
        {"question": "Bending Moment diagram shape for a cantilever beam with a point load at free end:", "options": ["Rectangular", "Triangular", "Parabolic", "Cubic"], "correct": 1, "explanation": "BM increases linearly from zero at free end to maximum at fixed support \u2014 triangular shape.", "difficulty": "easy", "source": "SOM \u2014 Cantilever BMD"},
        {"question": "Effect of a concentrated couple (moment) on the Shear Force Diagram:", "options": ["Sudden increase", "Sudden decrease", "Changes sign", "No change"], "correct": 3, "explanation": "A concentrated couple causes no change in SFD; it only produces a sudden jump in the BMD.", "difficulty": "medium", "source": "SOM \u2014 SFD/BMD"},
        {"question": "The point where bending moment changes sign along a beam is called:", "options": ["Point of Inflection", "Point of Contraflexure", "Point of Zero Shear", "Elastic Point"], "correct": 1, "explanation": "Point of Contraflexure is where BM is zero and changes sign.", "difficulty": "easy", "source": "SOM \u2014 Beam Theory"},
        {"question": "Graph showing variation of a force effect at a point as a unit load moves across the span:", "options": ["Load Diagram", "Stress-Strain Curve", "Shear Force Diagram", "Influence Line Diagram"], "correct": 3, "explanation": "An Influence Line Diagram shows how a response (reaction, moment, shear) at a specific point varies as a unit load traverses the span.", "difficulty": "medium", "source": "SOM \u2014 Influence Lines"},
        {"question": "Material property allowing large plastic deformation before fracture, enabling wire drawing:", "options": ["Brittleness", "Hardness", "Ductility", "Elasticity"], "correct": 2, "explanation": "Ductility is the ability to deform plastically before fracture, essential for wire drawing.", "difficulty": "easy", "source": "SOM \u2014 Material Properties"},
        {"question": "The safe design stress legally allowed, kept below elastic limit:", "options": ["Yield Stress", "Ultimate Stress", "Rupture Stress", "Working Stress"], "correct": 3, "explanation": "Working stress is the permissible stress that a material can safely carry during service.", "difficulty": "easy", "source": "SOM \u2014 Design Stress"},
        {"question": "Mechanical test to determine a metal's resistance to sudden impact shocks:", "options": ["Fatigue Test", "Creep Test", "Impact Test", "Tensile Test"], "correct": 2, "explanation": "Impact tests (Izod, Charpy) measure toughness \u2014 the energy absorbed during high-rate loading.", "difficulty": "easy", "source": "SOM \u2014 Material Testing"},
        {"question": "Mechanical test to determine a material's capacity to resist cyclic stress variations without cracking:", "options": ["Hardness Test", "Fatigue Test", "Bend Test", "Torsion Test"], "correct": 1, "explanation": "Fatigue tests evaluate behaviour under repeated/fluctuating stresses \u2014 critical for rotating components.", "difficulty": "easy", "source": "SOM \u2014 Material Testing"},
        {"question": "Moment of Inertia for a rectangular section (b \u00d7 d) about its centroidal axis (Ixx):", "options": ["bd\u00b3/12", "db\u00b3/12", "bd\u00b3/36", "\u03c0d\u2074/64"], "correct": 0, "explanation": "The area moment of inertia of a rectangle about its centroidal axis parallel to base = bd\u00b3/12.", "difficulty": "easy", "source": "SOM \u2014 Moment of Inertia"},
        {"question": "Moment of Inertia for a solid circular section of diameter d:", "options": ["\u03c0d\u00b3/32", "\u03c0d\u2074/64", "\u03c0d\u2074/32", "\u03c0d\u00b2/4"], "correct": 1, "explanation": "Area moment of inertia of a solid circle about its centroidal axis = \u03c0d\u2074/64.", "difficulty": "easy", "source": "SOM \u2014 Moment of Inertia"},
        {"question": "Shape of Bending Moment diagram for a simply supported beam carrying UDL:", "options": ["Triangle", "Rectangle", "Parabola", "Cubic curve"], "correct": 2, "explanation": "For SS beam with UDL, BM varies parabolically with maximum at centre and zero at supports.", "difficulty": "easy", "source": "SOM \u2014 BMD Shapes"},
        {"question": "Shape of Shear Force diagram for a simply supported beam with point load at mid-span:", "options": ["Inclined straight line", "Horizontal line", "Two rectangles (positive and negative)", "Parabolic curve"], "correct": 2, "explanation": "SF is constant on each side of the point load with a sudden drop, creating rectangular shapes on each side.", "difficulty": "easy", "source": "SOM \u2014 SFD Shapes"},
        {"question": "For a cantilever beam with UDL, the Bending Moment diagram is:", "options": ["Triangular", "Parabolic", "Cubic", "Rectangular"], "correct": 1, "explanation": "BM varies as the square of the distance from the free end \u2014 parabolic.", "difficulty": "medium", "source": "SOM \u2014 Cantilever BMD"},
        {"question": "At the point of contraflexure, the bending moment is:", "options": ["Maximum", "Minimum", "Zero", "Infinity"], "correct": 2, "explanation": "Point of contraflexure is where BM changes sign \u2014 its value is zero at that point.", "difficulty": "easy", "source": "SOM \u2014 Beam Theory"},
        {"question": "Which of the following is a statically determinate beam?", "options": ["Fixed beam", "Continuous beam", "Propped cantilever", "Simply supported beam"], "correct": 3, "explanation": "A simply supported beam has 3 unknowns and 3 equilibrium equations \u2192 statically determinate.", "difficulty": "easy", "source": "SOM \u2014 Structural Analysis"},
        {"question": "The unit of moment of inertia (area moment) is:", "options": ["m\u2074", "m\u00b3", "m\u00b2", "m"], "correct": 0, "explanation": "Moment of inertia = area \u00d7 distance\u00b2 \u2192 m\u00b2 \u00d7 m\u00b2 = m\u2074.", "difficulty": "easy", "source": "SOM \u2014 Moment of Inertia"},
        {"question": "Section modulus (Z) for a rectangular section of width b and depth d:", "options": ["bd\u00b2/6", "b\u00b2d/6", "bd\u00b3/12", "bd\u00b2/12"], "correct": 0, "explanation": "Z = I/y_max = (bd\u00b3/12)/(d/2) = bd\u00b2/6.", "difficulty": "medium", "source": "SOM \u2014 Section Properties"},
        {"question": "Which of the following is a measure of a material's stiffness?", "options": ["Poisson's ratio", "Modulus of Elasticity (E)", "Modulus of Rigidity (G)", "Bulk Modulus (K)"], "correct": 1, "explanation": "Young's Modulus (E) relates stress to strain in the elastic range, defining resistance to deformation.", "difficulty": "easy", "source": "SOM \u2014 Elastic Constants"},
        {"question": "Hooke's law holds up to which point on the stress-strain curve?", "options": ["Yield point", "Proportional limit", "Ultimate stress point", "Breaking point"], "correct": 1, "explanation": "Hooke's law (stress \u221d strain) is valid only up to the proportional limit.", "difficulty": "easy", "source": "SOM \u2014 Hooke's Law"},
        {"question": "The ratio of lateral strain to longitudinal strain is called:", "options": ["Modulus of Rigidity", "Bulk Modulus", "Poisson's Ratio", "Elastic Limit"], "correct": 2, "explanation": "Poisson's ratio \u03bd = \u2212(lateral strain)/(longitudinal strain).", "difficulty": "easy", "source": "SOM \u2014 Elastic Constants"},
        {"question": "A material that fails in tension with very little plastic deformation is called:", "options": ["Ductile", "Brittle", "Elastic", "Tough"], "correct": 1, "explanation": "Brittle materials (cast iron, glass, concrete) fracture suddenly with negligible plastic strain.", "difficulty": "easy", "source": "SOM \u2014 Material Properties"},
        {"question": "The theoretical maximum value of Poisson's ratio for an isotropic material is:", "options": ["0.25", "0.30", "0.50", "0.75"], "correct": 2, "explanation": "For an incompressible material (e.g., rubber), Poisson's ratio approaches 0.5.", "difficulty": "medium", "source": "SOM \u2014 Elastic Constants"},
        {"question": "The modulus of rigidity (G) is defined as the ratio of:", "options": ["Normal stress to normal strain", "Shear stress to shear strain", "Volumetric stress to volumetric strain", "Lateral strain to longitudinal strain"], "correct": 1, "explanation": "Shear modulus G = \u03c4/\u03b3 (shear stress / shear strain).", "difficulty": "easy", "source": "SOM \u2014 Elastic Constants"},
        {"question": "The relationship between E, G and K (elastic constants):", "options": ["E = 2G(1+\u03bc) only", "E = 3K(1-2\u03bc) only", "Both E = 2G(1+\u03bc) and E = 3K(1-2\u03bc)", "None of the above"], "correct": 2, "explanation": "Both E = 2G(1+\u03bc) and E = 3K(1-2\u03bc) are standard elastic constants relationships.", "difficulty": "medium", "source": "SOM \u2014 Elastic Constants"},
        {"question": "The maximum deflection in a simply supported beam with central point load occurs at:", "options": ["Supports", "Quarter span", "Mid-span", "One-third span"], "correct": 2, "explanation": "Due to symmetry, maximum deflection under a central point load is at mid-span.", "difficulty": "easy", "source": "SOM \u2014 Beam Deflection"},
        {"question": "The slope of the elastic curve at a point in a beam equals:", "options": ["Shear force / EI", "BM / EI", "Integral of M/EI dx", "Load intensity / EI"], "correct": 2, "explanation": "Slope \u03b8 = \u222b(M/EI)dx from the moment-curvature relationship of beams.", "difficulty": "hard", "source": "SOM \u2014 Beam Deflection"},
    ],
    "RCC_Steel": [
        {"question": "The minimum grade of concrete recommended for RCC structures as per IS 456 is ___", "options": ["M10", "M15", "M20", "M25"], "correct": 2, "explanation": "IS 456:2000 recommends M20 (20 MPa characteristic compressive strength) as the minimum grade for general RCC structures.", "difficulty": "easy", "source": "IS 456:2000 \u2014 Concrete Design"},
        {"question": "Water-cement ratio has a direct effect on ___", "options": ["Workability and strength of concrete", "Color of concrete only", "Setting time of cement only", "Weight of concrete only"], "correct": 0, "explanation": "W/C ratio is the most important factor affecting both workability (higher W/C \u2192 more workable) and strength (lower W/C \u2192 higher strength) of concrete.", "difficulty": "easy", "source": "Concrete Technology \u2014 Mix Design"},
        {"question": "Cover to reinforcement in concrete is provided to protect against ___", "options": ["Corrosion and fire", "Increase strength", "Reduce cost", "Increase weight"], "correct": 0, "explanation": "Adequate concrete cover protects steel reinforcement from corrosion (moisture and carbonation) and also provides fire resistance.", "difficulty": "easy", "source": "IS 456 \u2014 Cover to Reinforcement"},
        {"question": "The slump test for concrete measures ___", "options": ["Compressive strength", "Workability (consistency)", "Tensile strength", "Water content"], "correct": 1, "explanation": "The slump test measures the workability/consistency of fresh concrete \u2014 how easily it flows and fills the formwork.", "difficulty": "easy", "source": "Concrete Technology \u2014 Workability Tests"},
        {"question": "In a doubly reinforced beam, compression reinforcement is provided to ___", "options": ["Increase the tensile capacity", "Reduce depth when depth is restricted and single reinforcement is insufficient", "Reduce the shear", "Improve aesthetics"], "correct": 1, "explanation": "Doubly reinforced beams are used when beam depth is restricted and the moment exceeds the capacity of a singly reinforced section.", "difficulty": "medium", "source": "RCC Design \u2014 Beams"},
        {"question": "As per IS 456, the maximum water-cement ratio for moderate exposure conditions is ___", "options": ["0.45", "0.50", "0.55", "0.60"], "correct": 1, "explanation": "For moderate exposure conditions (as per IS 456:2000 Table 5), the maximum W/C ratio is 0.50.", "difficulty": "medium", "source": "IS 456:2000 \u2014 Durability"},
        {"question": "Minimum clear cover for an RCC slab (IS 456)?", "options": ["10 mm", "15 mm or bar diameter (whichever greater)", "25 mm", "40 mm"], "correct": 1, "explanation": "IS 456 specifies minimum clear cover of 15 mm for slabs, not less than bar diameter.", "difficulty": "easy", "source": "IS 456:2000 \u2014 cl. 26.4"},
        {"question": "Minimum clear cover for an RCC beam (IS 456)?", "options": ["15 mm", "20 mm", "25 mm or bar diameter (whichever greater)", "40 mm"], "correct": 2, "explanation": "IS 456 prescribes nominal cover of 25 mm for beams, subject to durability.", "difficulty": "easy", "source": "IS 456:2000 \u2014 cl. 26.4"},
        {"question": "Minimum clear cover for an RCC column (IS 456)?", "options": ["20 mm", "25 mm", "40 mm or bar diameter (whichever greater)", "50 mm"], "correct": 2, "explanation": "IS 456 specifies nominal cover of 40 mm for columns.", "difficulty": "easy", "source": "IS 456:2000 \u2014 cl. 26.4"},
        {"question": "Minimum clear cover for a foundation footing (IS 456)?", "options": ["25 mm", "40 mm", "50 mm", "75 mm"], "correct": 2, "explanation": "IS 456 specifies minimum 50 mm clear cover for footings to protect against soil contact.", "difficulty": "easy", "source": "IS 456:2000 \u2014 cl. 26.4.2"},
        {"question": "Maximum final setting time for OPC as per IS 269?", "options": ["30 minutes", "1 hour", "6 hours", "10 hours (600 minutes)"], "correct": 3, "explanation": "IS 269 prescribes a maximum final setting time of 600 minutes (10 hours) for OPC.", "difficulty": "easy", "source": "IS 269 \u2014 OPC Specification"},
        {"question": "Minimum initial setting time for OPC as per IS 269?", "options": ["30 minutes", "1 hour", "2 hours", "5 hours"], "correct": 0, "explanation": "OPC must have initial setting time of at least 30 minutes to allow mixing, transporting, and placing.", "difficulty": "easy", "source": "IS 269 \u2014 OPC Specification"},
        {"question": "Grade range for 'Standard Concrete' as per IS 456:2000?", "options": ["M10 to M20", "M15 to M30", "M20 to M50", "M25 to M55"], "correct": 3, "explanation": "IS 456:2000 Table 2 classifies M25 to M55 as Standard Concrete.", "difficulty": "medium", "source": "IS 456:2000 \u2014 Table 2"},
        {"question": "What does M20 concrete specification mean?", "options": ["Average strength of 20 N/mm\u00b2", "Minimum characteristic strength of 20 N/mm\u00b2 at 28 days", "Tensile strength of 20 N/mm\u00b2", "Flexural strength of 20 N/mm\u00b2"], "correct": 1, "explanation": "M20 \u2192 characteristic compressive strength (fck) = 20 N/mm\u00b2 at 28 days; not more than 5% of cubes fail below this.", "difficulty": "easy", "source": "IS 456:2000 \u2014 Notation"},
        {"question": "Standard slump range for mass concrete works?", "options": ["0 to 25 mm", "25 to 75 mm", "50 to 100 mm", "100 to 150 mm"], "correct": 1, "explanation": "For mass concrete (foundations), slump of 25-75 mm provides adequate workability for placement.", "difficulty": "easy", "source": "IS 456 \u2014 Workability"},
        {"question": "Minimum stripping time for side formwork of columns and beams?", "options": ["6 to 8 hours", "16 to 24 hours", "3 to 4 days", "7 days"], "correct": 1, "explanation": "Vertical formwork is removed after 16-24 hours once concrete gains enough strength to hold its own weight.", "difficulty": "easy", "source": "IS 456:2000 \u2014 Formwork"},
        {"question": "Minimum stripping time for props supporting slabs up to 4.5 m span?", "options": ["3 days", "7 days", "14 days", "21 days"], "correct": 1, "explanation": "IS 456 specifies minimum 7 days for props under slabs with span < 4.5 m.", "difficulty": "easy", "source": "IS 456:2000 \u2014 Formwork cl.11"},
        {"question": "Minimum stripping time for props supporting beams with spans up to 6.0 m?", "options": ["7 days", "10 days", "14 days", "21 days"], "correct": 2, "explanation": "IS 456 specifies minimum 14 days for props under beams with span < 6 m.", "difficulty": "easy", "source": "IS 456:2000 \u2014 Formwork cl.11"},
        {"question": "Minimum curing period for concrete when blended cements are used?", "options": ["7 days", "10 days", "14 days", "28 days"], "correct": 2, "explanation": "Blended cements (PPC, PSC) gain strength slowly; IS 456 recommends 14 days curing.", "difficulty": "easy", "source": "IS 456:2000 \u2014 Curing"},
        {"question": "Number of concrete cube samples required for a batch volume of 31-50 m\u00b3?", "options": ["1 Sample", "2 Samples", "3 Samples", "4 Samples"], "correct": 3, "explanation": "IS 456 Table 1: for 31-50 m\u00b3 concrete quantity, 4 samples are required.", "difficulty": "medium", "source": "IS 456:2000 \u2014 Table 1"},
        {"question": "Field NDT test to measure surface hardness of concrete?", "options": ["UPV test", "Rebound Hammer test", "Core Cut test", "Slump test"], "correct": 1, "explanation": "Rebound Hammer (Schmidt Hammer) measures surface hardness correlating to compressive strength.", "difficulty": "easy", "source": "IS 13311 \u2014 NDT"},
        {"question": "Field NDT test to measure internal homogeneity of concrete?", "options": ["Rebound Hammer test", "Probe Penetration test", "Ultrasonic Pulse Velocity (UPV) test", "Pull-out test"], "correct": 2, "explanation": "UPV test sends ultrasonic pulses through concrete to detect voids, cracks, and inhomogeneities.", "difficulty": "easy", "source": "IS 13311 \u2014 NDT"},
        {"question": "Minimum bar diameter for main longitudinal reinforcement in an RCC column?", "options": ["8 mm", "10 mm", "12 mm", "16 mm"], "correct": 2, "explanation": "IS 456 mandates minimum 12 mm diameter for column longitudinal bars to prevent buckling.", "difficulty": "easy", "source": "IS 456:2000 \u2014 cl.26.5.3"},
        {"question": "Minimum number of longitudinal bars in a circular RCC column?", "options": ["4", "6", "8", "10"], "correct": 1, "explanation": "IS 456: for circular or helical reinforced columns, minimum 6 longitudinal bars required.", "difficulty": "easy", "source": "IS 456:2000 \u2014 cl.26.5.3.1"},
        {"question": "Minimum thickness for an RCC slab as per standard codes?", "options": ["100 mm", "125 mm", "150 mm", "200 mm"], "correct": 1, "explanation": "Standard codes specify minimum 125 mm slab thickness for adequate stiffness and fire resistance.", "difficulty": "easy", "source": "IS 456:2000 \u2014 Slab Design"},
        {"question": "Standard design density for Reinforced Cement Concrete (RCC)?", "options": ["20 kN/m\u00b3", "22 kN/m\u00b3", "24 kN/m\u00b3", "25 kN/m\u00b3"], "correct": 3, "explanation": "Unit weight of RCC is taken as 25 kN/m\u00b3 (2500 kg/m\u00b3) accounting for steel reinforcement.", "difficulty": "easy", "source": "IS 875 \u2014 Dead Load"},
        {"question": "Maximum permissible diameter of rebar in an RCC slab of thickness 't'?", "options": ["t/4", "t/6", "t/8", "t/10"], "correct": 2, "explanation": "Bar diameter in a slab is limited to t/8 to prevent excessive cracking and ensure proper cover.", "difficulty": "medium", "source": "IS 456:2000 \u2014 Slab Design"},
        {"question": "Maximum reinforcement area percentage permitted in an RCC beam (IS 456)?", "options": ["2%", "3%", "4%", "5%"], "correct": 2, "explanation": "IS 456 cl.26.5.1 restricts total steel in a beam to 4% of gross cross-sectional area.", "difficulty": "easy", "source": "IS 456:2000 \u2014 cl.26.5.1"},
        {"question": "What side face reinforcement is needed if RCC beam depth exceeds 750 mm?", "options": ["Temperature reinforcement", "Side face reinforcement", "Torsion reinforcement", "Additional stirrups"], "correct": 1, "explanation": "IS 456 cl.26.5.1.3: for webs deeper than 750 mm, side face reinforcement controls web cracking.", "difficulty": "medium", "source": "IS 456:2000 \u2014 cl.26.5.1.3"},
        {"question": "At what height is a counterfort retaining wall typically used?", "options": ["Less than 3 m", "3 m to 6 m", "Greater than 6 m", "Always"], "correct": 2, "explanation": "For walls > 6 m, bending moments become large; counterforts connect stem to base slab for economy.", "difficulty": "medium", "source": "RCC Design \u2014 Retaining Walls"},
        {"question": "Standard single commercial length of a reinforcing steel rod?", "options": ["6 m", "9 m", "12 m", "15 m"], "correct": 2, "explanation": "Standard length of commercial TMT/HYSD bar is 12 metres for handling and transport.", "difficulty": "easy", "source": "IS 1786 \u2014 Steel Bars"},
        {"question": "Beyond what diameter is manual lap splicing not recommended on Indian Railways?", "options": ["20 mm", "25 mm", "32 mm", "36 mm"], "correct": 3, "explanation": "For bars > 36 mm diameter, mechanical couplers or welding are required for proper load transfer on Indian Railways.", "difficulty": "medium", "source": "IR Bridge Manual / IS 456"},
        {"question": "Minimum 28-day cube strength for pre-tensioned concrete (IS 1343)?", "options": ["35 N/mm\u00b2", "40 N/mm\u00b2", "45 N/mm\u00b2", "50 N/mm\u00b2"], "correct": 2, "explanation": "IS 1343:2012 specifies minimum M45 (45 N/mm\u00b2) for pre-tensioned concrete.", "difficulty": "medium", "source": "IS 1343:2012 \u2014 Prestressed Concrete"},
        {"question": "Minimum 28-day cube strength for post-tensioned concrete (IS 1343)?", "options": ["35 N/mm\u00b2", "40 N/mm\u00b2", "45 N/mm\u00b2", "50 N/mm\u00b2"], "correct": 0, "explanation": "IS 1343:2012 specifies minimum M35 (35 N/mm\u00b2) for post-tensioned concrete.", "difficulty": "medium", "source": "IS 1343:2012 \u2014 Prestressed Concrete"},
        {"question": "What does Abrams' water-cement ratio law state?", "options": ["Strength depends on cement content", "Strength depends on water-cement ratio", "Strength depends on aggregate size", "Strength depends on curing conditions"], "correct": 1, "explanation": "Abrams' Law: strength of concrete is primarily a function of its water-cement ratio for workable mixes.", "difficulty": "easy", "source": "Concrete Technology \u2014 Abrams' Law"},
        {"question": "Definition of Characteristic Strength (fck)?", "options": ["Average strength of all cubes", "Maximum strength achieved", "Strength below which not more than 5% of test results fall", "Minimum strength specified by designer"], "correct": 2, "explanation": "fck: value of compressive strength below which not more than 5% of test results are expected to fall.", "difficulty": "easy", "source": "IS 456:2000 \u2014 Definitions"},
        {"question": "Three standard laboratory tests for workability of concrete?", "options": ["Sieve analysis, Slump test, Vee-Bee test", "Slump test, Vee-Bee test, Compaction factor test", "Compression test, Slump test, Compaction factor test", "Tensile test, Vee-Bee test, Slump test"], "correct": 1, "explanation": "Slump test, Vee-Bee consistometer test, and Compaction factor test are the three standard workability tests.", "difficulty": "medium", "source": "IS 1199 \u2014 Workability Tests"},
        {"question": "If L/B ratio of a slab > 2, it is designed as:", "options": ["Two-way slab", "Flat slab", "One-way slab", "Ribbed slab"], "correct": 2, "explanation": "Slabs with aspect ratio L/B > 2 are one-way slabs; they primarily bend in the short direction.", "difficulty": "easy", "source": "IS 456:2000 \u2014 Slab Design"},
        {"question": "If L/B ratio of a slab \u2264 2, it is designed as:", "options": ["One-way slab", "Two-way slab", "Cantilever slab", "Grid slab"], "correct": 1, "explanation": "Slabs with L/B \u2264 2 are two-way slabs \u2014 loads transfer in both directions to supports.", "difficulty": "easy", "source": "IS 456:2000 \u2014 Slab Design"},
        {"question": "An RCC beam where actual neutral axis depth exceeds critical neutral axis depth:", "options": ["Balanced beam", "Under-reinforced beam", "Over-reinforced beam", "Doubly-reinforced beam"], "correct": 2, "explanation": "Over-reinforced beam: concrete crushes before steel yields \u2014 sudden brittle failure (undesirable).", "difficulty": "medium", "source": "IS 456:2000 \u2014 Beam Design"},
        {"question": "Three classical Post-Tensioning systems?", "options": ["Freyssinet, Hoyer, Magnel-Blaton", "Gifford-Udall, Lee-McCall, Longline", "Freyssinet, Magnel-Blaton, Lee-McCall", "Pre-tensioning, Hoyer, Magnel"], "correct": 2, "explanation": "Classical post-tensioning systems: Freyssinet system, Magnel-Blaton system, Lee-McCall system.", "difficulty": "hard", "source": "IS 1343 \u2014 Prestressed Concrete Systems"},
        {"question": "A beam is said to be 'under-reinforced' when:", "options": ["Steel yields before concrete crushes", "Concrete crushes before steel yields", "Both reach failure simultaneously", "Steel does not yield at all"], "correct": 0, "explanation": "Under-reinforced beams fail by steel yielding first \u2014 ductile failure with prior warning.", "difficulty": "medium", "source": "IS 456:2000 \u2014 Beam Design"},
        {"question": "In a doubly reinforced beam, the additional steel is provided in the:", "options": ["Tension zone only", "Compression zone only", "Both tension and compression zones", "Web only"], "correct": 1, "explanation": "Compression reinforcement is added in compression zone to increase moment capacity when section size is limited.", "difficulty": "medium", "source": "IS 456:2000 \u2014 Doubly Reinforced Beams"},
        {"question": "The neutral axis depth in a balanced RC beam is determined by:", "options": ["Load factor", "Steel yield strain and concrete ultimate strain", "Span/depth ratio", "Cover to reinforcement"], "correct": 1, "explanation": "Balanced condition: steel reaches yield strain exactly when concrete reaches ultimate strain (0.0035 per IS 456).", "difficulty": "hard", "source": "IS 456:2000 \u2014 Balanced Section"},
        {"question": "The term 'effective depth' of a beam means:", "options": ["Total depth minus cover", "Distance from compression face to centroid of tension reinforcement", "Distance between tension and compression reinforcement", "Depth up to centre of beam"], "correct": 1, "explanation": "Effective depth d = overall depth \u2013 clear cover \u2013 half bar diameter.", "difficulty": "easy", "source": "IS 456:2000 \u2014 Definitions"},
        {"question": "Depth of equivalent rectangular stress block for RCC beam as per IS 456:", "options": ["0.36 xu", "0.42 xu", "0.48 xu", "0.87 xu"], "correct": 1, "explanation": "IS 456:2000: depth of rectangular stress block = 0.42 \u00d7 neutral axis depth (xu).", "difficulty": "hard", "source": "IS 456:2000 \u2014 cl.38.1"},
        {"question": "Limiting neutral axis depth (xu,max) for Fe415 steel (IS 456):", "options": ["0.48 d", "0.46 d", "0.53 d", "0.67 d"], "correct": 0, "explanation": "IS 456 cl.38.1: for Fe415 steel, xu,max/d = 0.48.", "difficulty": "hard", "source": "IS 456:2000 \u2014 cl.38.1"},
        {"question": "A beam is called 'deep beam' when its span-to-depth ratio is less than:", "options": ["1.0", "2.0", "2.5", "3.0"], "correct": 1, "explanation": "IS 456: beams with clear span < 2 \u00d7 effective depth are designed as deep beams.", "difficulty": "medium", "source": "IS 456:2000 \u2014 cl.29"},
        {"question": "Purpose of providing stirrups in a beam:", "options": ["Resist compressive stress", "Resist shear stress and diagonal tension", "Resist bond stress", "Resist temperature stress"], "correct": 1, "explanation": "Stirrups (vertical or inclined links) resist shear and diagonal tensile cracks in beams.", "difficulty": "easy", "source": "IS 456:2000 \u2014 Shear Design"},
        {"question": "Development length of a bar depends on:", "options": ["Bar diameter only", "Steel grade and concrete grade", "Bar diameter, steel stress, and bond strength", "Length of beam"], "correct": 2, "explanation": "Ld = (\u03c6 \u03c3s)/(4 \u03c4bd) \u2014 depends on bar diameter \u03c6, steel stress \u03c3s, and design bond stress \u03c4bd.", "difficulty": "medium", "source": "IS 456:2000 \u2014 cl.26.2"},
        {"question": "A short column is one for which slenderness ratio (leff/least lateral dimension) is less than:", "options": ["6", "12", "16", "18"], "correct": 1, "explanation": "IS 456: column is short if leff/D < 12; otherwise it is slender and buckling must be considered.", "difficulty": "medium", "source": "IS 456:2000 \u2014 cl.25.1.2"},
        {"question": "Helical reinforcement in a column increases its load capacity by approximately:", "options": ["5%", "10%", "15%", "20%"], "correct": 0, "explanation": "IS 456 allows 5% increase in load-carrying capacity for columns with helical confinement reinforcement.", "difficulty": "medium", "source": "IS 456:2000 \u2014 cl.39.4"},
        {"question": "Minimum eccentricity to be considered in design of axially loaded columns (IS 456):", "options": ["10 mm", "20 mm", "Greater of (l/500) and (D/30) but not less than 20 mm", "50 mm"], "correct": 2, "explanation": "IS 456 cl.25.4: minimum eccentricity = max(l/500, D/30) with a minimum of 20 mm.", "difficulty": "hard", "source": "IS 456:2000 \u2014 cl.25.4"},
        {"question": "Critical section for maximum BM in a cantilever retaining wall:", "options": ["Top of wall", "Junction of stem with base slab", "Mid-height", "Heel of base slab"], "correct": 1, "explanation": "Maximum bending moment in retaining wall stem occurs at its junction with the base slab.", "difficulty": "medium", "source": "IS 456 \u2014 Retaining Wall Design"},
        {"question": "Minimum factor of safety against sliding for a retaining wall:", "options": ["1.0", "1.5", "2.0", "3.0"], "correct": 1, "explanation": "IS 456 and IR practice: FOS against sliding \u2265 1.5 for retaining walls.", "difficulty": "medium", "source": "IS 456:2000 / IR Practice"},
    ],
    "SoilMechanics": [
        {"question": "The shear strength of cohesionless soil (sand) depends on ___", "options": ["Cohesion only", "Angle of internal friction only", "Both cohesion and friction", "Plasticity index"], "correct": 1, "explanation": "In cohesionless soils like sand, cohesion c = 0, so shear strength depends entirely on the angle of internal friction (\u03c6) and normal stress.", "difficulty": "easy", "source": "Soil Mechanics \u2014 Shear Strength"},
        {"question": "Standard Penetration Test (SPT) is used to determine ___", "options": ["Bearing capacity and soil profile", "Consolidation settlement", "Permeability", "Swelling pressure"], "correct": 0, "explanation": "SPT gives N-value which is used to estimate bearing capacity of soil, soil classification, and degree of compaction in the field.", "difficulty": "easy", "source": "Soil Mechanics \u2014 Field Tests"},
        {"question": "Terzaghi's theory of consolidation is related to ___", "options": ["Shear failure of soil", "Time-dependent settlement of saturated clay under load", "Slope stability", "Bearing capacity"], "correct": 1, "explanation": "Terzaghi's consolidation theory describes the time-dependent process of pore water pressure dissipation and corresponding settlement in saturated clays under sustained load.", "difficulty": "medium", "source": "Soil Mechanics \u2014 Consolidation"},
        {"question": "The angle of repose of a soil is ___", "options": ["Equal to angle of internal friction", "The slope angle at which a soil heap remains stable without support", "The angle of maximum shear stress", "Always 30 degrees"], "correct": 1, "explanation": "Angle of repose is the steepest angle at which a granular material will remain stable on its own without any support \u2014 approximately equal to angle of internal friction for dry sand.", "difficulty": "medium", "source": "Soil Mechanics \u2014 Shear Strength"},
        {"question": "Atterberg limits are used to classify ___", "options": ["Sandy soils", "Fine-grained cohesive soils (silts and clays)", "Gravels", "All soils equally"], "correct": 1, "explanation": "Atterberg limits (Liquid Limit, Plastic Limit, Shrinkage Limit) are applicable to fine-grained soils (silts and clays) to define their consistency and plasticity.", "difficulty": "easy", "source": "Soil Mechanics \u2014 Soil Classification"},
        {"question": "Soil with minimum coefficient of permeability:", "options": ["Sand", "Gravel", "Silt", "Clay"], "correct": 3, "explanation": "Clay has very small pore spaces and high surface friction \u2014 extremely low permeability compared to granular soils.", "difficulty": "easy", "source": "Soil Mechanics \u2014 Permeability"},
        {"question": "Definition of Plastic Limit (Wp):", "options": ["Water content at which soil flows", "Water content at which soil crumbles when rolled into 3 mm thread", "Water content at which soil volume changes", "Water content at which soil is saturated"], "correct": 1, "explanation": "Plastic Limit: water content below which soil stops behaving plastically and begins to crumble.", "difficulty": "easy", "source": "Soil Mechanics \u2014 Atterberg Limits"},
        {"question": "Classification of Under-Reamed Piles:", "options": ["Steel piles", "Timber piles", "Driven cast-in-situ piles", "Bored cast-in-situ concrete piles"], "correct": 3, "explanation": "Under-reamed piles are bored, cast-in-situ concrete piles with enlarged bulb(s) at bottom for uplift resistance.", "difficulty": "medium", "source": "IS 2911 \u2014 Pile Foundations"},
        {"question": "Height of application of active earth pressure resultant on a retaining wall:", "options": ["H/2 from base", "H/3 from base", "H/2 from top", "H/3 from top"], "correct": 1, "explanation": "For level backfill, resultant active earth pressure acts at H/3 above base of retaining wall.", "difficulty": "medium", "source": "Soil Mechanics \u2014 Rankine's Theory"},
        {"question": "Field test to determine safe bearing capacity and settlement:", "options": ["Standard Penetration Test (SPT)", "Vane Shear Test", "Cone Penetration Test", "Plate Load Test"], "correct": 3, "explanation": "Plate Load Test: load applied to steel plate at foundation level; settlement measured to estimate bearing capacity.", "difficulty": "medium", "source": "IS 1888 \u2014 Plate Load Test"},
        {"question": "Moisture boundary between plastic and liquid state of soil:", "options": ["Plastic Limit", "Shrinkage Limit", "Liquid Limit", "Flow Limit"], "correct": 2, "explanation": "Liquid Limit (LL): water content at which soil behaviour transitions from plastic solid to liquid mass.", "difficulty": "easy", "source": "Soil Mechanics \u2014 Atterberg Limits"},
        {"question": "Formula for Plasticity Index (Ip):", "options": ["Ip = Wl + Wp", "Ip = Wl \u2212 Wp", "Ip = Wp/Wl", "Ip = Wl \u00d7 Wp"], "correct": 1, "explanation": "Plasticity Index Ip = LL \u2212 PL (range of moisture over which soil remains plastic).", "difficulty": "easy", "source": "Soil Mechanics \u2014 Atterberg Limits"},
        {"question": "Contact pressure distribution under a rigid footing on clay:", "options": ["Maximum at centre, minimum at edges", "Minimum at centre, maximum at edges", "Uniformly distributed", "Random"], "correct": 1, "explanation": "Rigid footing settles uniformly; for clay, contact pressure is higher at edges to maintain uniform settlement.", "difficulty": "hard", "source": "Soil Mechanics \u2014 Foundation Pressure"},
        {"question": "Definition of Ultimate Bearing Capacity:", "options": ["Gross pressure at which soil fails in shear", "Safe pressure a soil can carry", "Net pressure a soil can carry", "Pressure at which footing settles 25 mm"], "correct": 0, "explanation": "Ultimate Bearing Capacity (q_ult): minimum gross pressure at foundation base causing shear failure in soil.", "difficulty": "medium", "source": "Soil Mechanics \u2014 Bearing Capacity"},
        {"question": "Deep foundation adopted underwater for heavy bridge piers:", "options": ["Pile Foundation", "Caisson / Well Foundation", "Raft Foundation", "Grillage Foundation"], "correct": 1, "explanation": "Caisson/well foundations are large watertight structures sunk into place \u2014 ideal for deep underwater bridge piers.", "difficulty": "easy", "source": "IRBM \u2014 Foundation Types"},
        {"question": "For which soil type are under-reamed piles best suited?", "options": ["Soft sand", "Dense gravel", "Black Cotton Soil (Expansive)", "Hard rock"], "correct": 2, "explanation": "Under-reamed piles designed for expansive soils like Black Cotton Soil; resist swelling/shrinkage movements.", "difficulty": "medium", "source": "IS 2911 \u2014 Under-reamed Piles"},
        {"question": "Definition of Porosity (n) in soil:", "options": ["Ratio of voids to solids volume", "Ratio of water to voids volume", "Ratio of voids to total volume", "Ratio of solids to total volume"], "correct": 2, "explanation": "Porosity n = Vv/V (volume of voids / total volume of soil).", "difficulty": "easy", "source": "Soil Mechanics \u2014 Phase Relations"},
        {"question": "Definition of Voids Ratio (e) in soil:", "options": ["Ratio of voids to total volume", "Ratio of voids to solids volume", "Ratio of water to voids volume", "Ratio of water to solids volume"], "correct": 1, "explanation": "Void ratio e = Vv/Vs (volume of voids / volume of solids).", "difficulty": "easy", "source": "Soil Mechanics \u2014 Phase Relations"},
        {"question": "Formula for Uniformity Coefficient (Cu):", "options": ["Cu = D10/D60", "Cu = D60/D10", "Cu = D30/D60", "Cu = D60 \u00d7 D10"], "correct": 1, "explanation": "Uniformity coefficient Cu = D60/D10 \u2014 measures range of particle sizes in soil.", "difficulty": "easy", "source": "Soil Mechanics \u2014 Gradation"},
        {"question": "Formula for Coefficient of Curvature (Cc):", "options": ["Cc = D30/(D60\u00d7D10)", "Cc = (D30)\u00b2/D10", "Cc = (D30)\u00b2/(D60\u00d7D10)", "Cc = D60/(D30\u00d7D10)"], "correct": 2, "explanation": "Cc = (D30)\u00b2/(D10 \u00d7 D60) \u2014 describes shape of particle size distribution curve.", "difficulty": "medium", "source": "Soil Mechanics \u2014 Gradation"},
        {"question": "Range of Coefficient of Curvature (Cc) for a well-graded soil:", "options": ["0 to 1", "1 to 3", "3 to 5", "Greater than 5"], "correct": 1, "explanation": "Well-graded soil has Cc between 1 and 3, indicating smooth gradation of particle sizes.", "difficulty": "medium", "source": "IS 2720 \u2014 Soil Classification"},
        {"question": "Compaction equipment for cohesive clay soils:", "options": ["Vibratory Roller", "Smooth Wheel Roller", "Sheep Foot Roller", "Grid Roller"], "correct": 2, "explanation": "Sheep foot roller's kneading action is ideal for compacting cohesive soils like clay.", "difficulty": "easy", "source": "Soil Mechanics \u2014 Compaction"},
        {"question": "Particle size range of Silt as per IS classification:", "options": ["0.075 mm to 4.75 mm", "0.002 mm to 0.075 mm", "Less than 0.002 mm", "Greater than 4.75 mm"], "correct": 1, "explanation": "IS classification: silt particles range from 0.002 mm to 0.075 mm.", "difficulty": "easy", "source": "IS 2720 \u2014 Soil Classification"},
        {"question": "Maximum loose layer thickness for embankment construction on Indian Railways:", "options": ["15 cm", "30 cm", "45 cm", "60 cm"], "correct": 1, "explanation": "IR specification: earthwork in embankments laid in horizontal layers not exceeding 300 mm (30 cm) loose.", "difficulty": "easy", "source": "IRPWM \u2014 Earthwork"},
        {"question": "Definition of Optimum Moisture Content (OMC):", "options": ["Minimum water content for saturation", "Water content for maximum dry density", "Water content for zero compaction", "Water content for maximum volume"], "correct": 1, "explanation": "OMC: specific moisture content at which soil is compacted to maximum dry density for a given compactive effort.", "difficulty": "easy", "source": "IS 2720 \u2014 Compaction Test"},
        {"question": "Temporary watertight enclosure built underwater for construction:", "options": ["Dyke", "Jetty", "Coffer Dam", "Training Wall"], "correct": 2, "explanation": "Coffer dam: temporary structure excluding water to create dry working area for foundation construction.", "difficulty": "easy", "source": "Foundation Engineering"},
        {"question": "Definition of Shrinkage Limit in soil:", "options": ["Water content at which volume decreases", "Water content at which cracks appear", "Water content below which no further volume change occurs", "Water content at which soil becomes liquid"], "correct": 2, "explanation": "Shrinkage Limit: water content at which further loss of moisture produces no decrease in soil volume.", "difficulty": "easy", "source": "Soil Mechanics \u2014 Atterberg Limits"},
        {"question": "Definition of Permeability of soil:", "options": ["Ability to resist shear", "Ability to permit water to pass through voids", "Ability to compress under load", "Ability to expand when wet"], "correct": 1, "explanation": "Permeability: property of porous material allowing fluids to flow through interconnected voids.", "difficulty": "easy", "source": "Soil Mechanics \u2014 Permeability"},
        {"question": "Standard spacing between bulbs in an under-reamed pile:", "options": ["0.5 times shaft diameter", "1.0 times shaft diameter", "1.5 times shaft diameter", "2.5 times shaft diameter"], "correct": 2, "explanation": "IS 2911: clear spacing of 1.5 times shaft diameter between successive bulbs for effective load transfer.", "difficulty": "medium", "source": "IS 2911 \u2014 Under-reamed Piles"},
        {"question": "Shallow foundation with network of steel I-beams on weak soils:", "options": ["Raft foundation", "Grillage foundation", "Combined footing", "Strap footing"], "correct": 1, "explanation": "Grillage foundation: tiers of steel I-beams in grid pattern embedded in concrete to distribute heavy loads.", "difficulty": "medium", "source": "Foundation Engineering"},
        {"question": "Laboratory method for grain size distribution of fine-grained soil (< 75 \u00b5m):", "options": ["Sieve analysis", "Hydrometer method", "Pipette method", "Both Hydrometer and Pipette methods"], "correct": 3, "explanation": "For particles finer than 75 \u00b5m, sedimentation-based Hydrometer or Pipette analysis is used.", "difficulty": "medium", "source": "IS 2720 \u2014 Grain Size Analysis"},
        {"question": "Uniformity Coefficient (Cu) for well-graded gravel:", "options": ["Cu > 2", "Cu > 4", "Cu > 6", "Cu > 10"], "correct": 1, "explanation": "IS 2720: for well-graded gravel, uniformity coefficient Cu > 4.", "difficulty": "medium", "source": "IS 2720 \u2014 Soil Classification"},
        {"question": "Uniformity Coefficient (Cu) for well-graded sand:", "options": ["Cu > 2", "Cu > 4", "Cu > 6", "Cu > 8"], "correct": 2, "explanation": "IS 2720: for well-graded sand, uniformity coefficient Cu > 6.", "difficulty": "medium", "source": "IS 2720 \u2014 Soil Classification"},
        {"question": "Foundation designed as a continuous thick slab to counter differential settlement:", "options": ["Strip footing", "Isolated footing", "Mat or Raft foundation", "Grillage foundation"], "correct": 2, "explanation": "Raft/mat foundation: large concrete slab over entire footprint, minimises differential settlement.", "difficulty": "easy", "source": "Foundation Engineering"},
        {"question": "Laboratory apparatus to determine OMC and Maximum Dry Density:", "options": ["Casagrande apparatus", "Triaxial apparatus", "Standard Proctor Test apparatus", "Permeameter"], "correct": 2, "explanation": "Standard Proctor Compaction Test (IS 2720 Part 7) determines OMC and Maximum Dry Density.", "difficulty": "easy", "source": "IS 2720 \u2014 Compaction Test"},
        {"question": "Coefficient of active earth pressure (Ka) for level backfill with \u03c6 = 30\u00b0:", "options": ["0.333", "0.5", "0.667", "1.0"], "correct": 0, "explanation": "Ka = (1\u2013sin\u03c6)/(1+sin\u03c6) = (1\u20130.5)/(1+0.5) = 0.5/1.5 = 1/3 \u2248 0.333", "difficulty": "medium", "source": "Soil Mechanics \u2014 Rankine's Theory"},
        {"question": "Coefficient of passive earth pressure (Kp) for \u03c6 = 30\u00b0:", "options": ["1.0", "2.0", "3.0", "4.0"], "correct": 2, "explanation": "Kp = (1+sin\u03c6)/(1\u2013sin\u03c6) = 1.5/0.5 = 3.0", "difficulty": "medium", "source": "Soil Mechanics \u2014 Rankine's Theory"},
        {"question": "Vertical cut in cohesive soil (\u03c6 = 0) can stand unsupported up to height of:", "options": ["2c/\u03b3", "4c/\u03b3", "6c/\u03b3", "8c/\u03b3"], "correct": 1, "explanation": "Critical height Hc = 4c/\u03b3 for \u03c6 = 0 soil (c = cohesion, \u03b3 = unit weight).", "difficulty": "hard", "source": "Soil Mechanics \u2014 Stability of Cuts"},
        {"question": "The liquid limit of a soil is determined using:", "options": ["Hydrometer", "Casagrande apparatus", "Proctor mould", "Triaxial cell"], "correct": 1, "explanation": "Casagrande's liquid limit apparatus (grooving tool and cup) is the standard method.", "difficulty": "easy", "source": "IS 2720 \u2014 Atterberg Limits"},
        {"question": "A soil has a plasticity index of zero. It is most likely:", "options": ["Clay", "Silt", "Sand", "Organic soil"], "correct": 2, "explanation": "Non-plastic soils (Ip = 0) include sands and gravels \u2014 no plastic behaviour.", "difficulty": "easy", "source": "Soil Mechanics \u2014 Plasticity"},
        {"question": "The standard Proctor test gives maximum dry density at which water content?", "options": ["Saturation water content", "Optimum Moisture Content (OMC)", "Liquid limit", "Shrinkage limit"], "correct": 1, "explanation": "OMC corresponds to the peak dry density on the Proctor compaction curve.", "difficulty": "easy", "source": "IS 2720 \u2014 Compaction"},
        {"question": "In a consolidation test, Cv is determined using:", "options": ["Taylor's \u221at method only", "Casagrande's log t method only", "Both Taylor's and Casagrande's methods", "Neither"], "correct": 2, "explanation": "Both Taylor's square root of time method and Casagrande's log t method are used to find Cv.", "difficulty": "medium", "source": "IS 2720 \u2014 Consolidation Test"},
        {"question": "The ultimate settlement of a foundation on clay is due to:", "options": ["Elastic compression only", "Primary consolidation only", "Secondary consolidation only", "All: elastic + primary + secondary consolidation"], "correct": 3, "explanation": "Total settlement = immediate (elastic) compression + primary consolidation + secondary (creep) consolidation.", "difficulty": "medium", "source": "Soil Mechanics \u2014 Settlement"},
        {"question": "Bearing capacity of soil improves if the water table:", "options": ["Rises to ground level", "Lowers below foundation depth", "Is at mid-height of footing", "Has no effect"], "correct": 1, "explanation": "Lowering water table increases effective stress in soil \u2192 increases bearing capacity.", "difficulty": "medium", "source": "Soil Mechanics \u2014 Bearing Capacity"},
        {"question": "A pile is called a 'friction pile' if it transfers load primarily by:", "options": ["End bearing", "Skin friction", "Both equally", "Negative skin friction"], "correct": 1, "explanation": "Friction piles rely on shaft resistance (skin friction) along their length to carry loads.", "difficulty": "easy", "source": "IS 2911 \u2014 Pile Foundations"},
        {"question": "Negative skin friction on a pile occurs when:", "options": ["Pile is loaded beyond capacity", "Surrounding soil settles more than the pile", "Soil is very dense", "Pile is driven into rock"], "correct": 1, "explanation": "Downdrag (negative skin friction) occurs when soft compressible soil settles, pulling the pile down.", "difficulty": "medium", "source": "IS 2911 \u2014 Pile Foundations"},
        {"question": "The group efficiency of piles in sand is generally:", "options": ["Less than 1", "Equal to 1", "Greater than 1", "Variable"], "correct": 2, "explanation": "In sand, pile group efficiency > 1 due to densification effect of adjacent piles.", "difficulty": "hard", "source": "Foundation Engineering \u2014 Pile Groups"},
        {"question": "Standard Penetration Number (N) is blows required to drive sampler for:", "options": ["First 150 mm", "Next 300 mm after 150 mm seating drive", "Last 450 mm", "Total 500 mm"], "correct": 1, "explanation": "N = number of blows for 300 mm penetration after initial 150 mm seating drive.", "difficulty": "medium", "source": "IS 2131 \u2014 SPT"},
        {"question": "For normally consolidated clay, coefficient of earth pressure at rest (K0):", "options": ["0.5", "1 \u2212 sin\u03c6", "1 + sin\u03c6", "0.33"], "correct": 1, "explanation": "Jaky's formula: K0 = 1 \u2212 sin\u03c6 for normally consolidated soils.", "difficulty": "medium", "source": "Soil Mechanics \u2014 Earth Pressure"},
        {"question": "Critical hydraulic gradient (ic) for quick sand condition:", "options": ["(G\u22121)/(1+e)", "(G+1)/(1+e)", "(G\u22121)\u00d7e", "(G\u22121)/e"], "correct": 0, "explanation": "ic = (G\u22121)/(1+e), where G = specific gravity of soil solids, e = void ratio.", "difficulty": "hard", "source": "Soil Mechanics \u2014 Seepage"},
        {"question": "In a triaxial test, the cell pressure represents the:", "options": ["Deviator stress", "Minor principal stress (\u03c33)", "Major principal stress (\u03c31)", "Pore pressure"], "correct": 1, "explanation": "In triaxial test: \u03c33 = cell pressure (confining stress); \u03c31 = \u03c33 + deviator stress.", "difficulty": "medium", "source": "Soil Mechanics \u2014 Triaxial Test"},
        {"question": "Vane shear test is most suitable for measuring undrained shear strength of:", "options": ["Soft clays", "Sands", "Gravels", "Rocks"], "correct": 0, "explanation": "Vane shear test is used for soft to medium cohesive soils, especially sensitive clays.", "difficulty": "easy", "source": "IS 2720 \u2014 Vane Shear Test"},
        {"question": "The angle of repose of a soil is approximately equal to its:", "options": ["Cohesion", "Angle of internal friction (\u03c6)", "Active earth pressure coefficient", "Poisson's ratio"], "correct": 1, "explanation": "Angle of repose \u2248 \u03c6 for dry cohesionless soil \u2014 slope angle at which granular material is stable.", "difficulty": "easy", "source": "Soil Mechanics \u2014 Shear Strength"},
        {"question": "In a flow net, the region between two successive flow lines is called a:", "options": ["Flow channel", "Equipotential drop", "Phreatic line", "Seepage face"], "correct": 0, "explanation": "A flow channel is the area bounded by two adjacent flow lines in a flow net.", "difficulty": "medium", "source": "Soil Mechanics \u2014 Seepage"},
        {"question": "Phreatic line in an earth dam is the:", "options": ["Top-most flow line only", "Line of zero pore pressure only", "Line of maximum seepage velocity", "Both top-most flow line and line of zero pore pressure"], "correct": 3, "explanation": "The phreatic line is the top flow line where pore pressure = atmospheric (zero gauge pressure).", "difficulty": "medium", "source": "Soil Mechanics \u2014 Seepage"},
        {"question": "Factor of safety against boiling (quick sand) is defined as:", "options": ["ic / i", "i / ic", "\u03b3sub / \u03b3w", "\u03b3sat / \u03b3w"], "correct": 0, "explanation": "FOS against quicksand = critical hydraulic gradient (ic) / actual hydraulic gradient (i).", "difficulty": "medium", "source": "Soil Mechanics \u2014 Seepage Failure"},
    ],
    "PHE": [
        {"question": "As per IRWM, the amount of residual chlorine in public water supply for safety against pathogenic bacteria is about ___", "options": ["0.2 mg/L", "0.6 mg/L", "0.8 mg/L", "1.0 to 5.0 ppm"], "correct": 0, "explanation": "Residual chlorine of 0.2 mg/L at the consumer end is maintained to ensure water remains safe against pathogenic bacteria during distribution.", "difficulty": "easy", "source": "IRWM / PHE \u2014 Water Supply"},
        {"question": "Provision of septic tanks with soak pit/filter bed is NOT appropriate for toilets of colony in ___", "options": ["Platform at small stations", "Gate lodge quarters in mid-section", "Heavily built-up urban areas", "Rural railway colonies"], "correct": 2, "explanation": "In heavily built-up urban areas, septic tanks are unsuitable due to space constraints and the availability of municipal sewage systems.", "difficulty": "easy", "source": "IRWM \u2014 Sanitation Systems"},
        {"question": "For design of sewage system, as per IRWM, ___ of water supplied is considered to reach sewers.", "options": ["90%", "80%", "75%", "70%"], "correct": 2, "explanation": "IRWM specifies that 75% of the daily water supply should be taken as the sewage flow rate for sewer design purposes.", "difficulty": "easy", "source": "IRWM \u2014 Sewage Design"},
        {"question": "The most effective method of disinfection of water supply is ___", "options": ["Boiling", "Filtration", "Chlorination", "UV treatment"], "correct": 2, "explanation": "Chlorination is the most common and cost-effective method of disinfection of water supply, providing residual protection during distribution.", "difficulty": "easy", "source": "PHE \u2014 Water Treatment"},
        {"question": "BOD (Biochemical Oxygen Demand) is an indicator of ___", "options": ["Amount of dissolved oxygen", "Degree of organic pollution in water", "Hardness of water", "Turbidity of water"], "correct": 1, "explanation": "BOD measures the amount of dissolved oxygen consumed by microorganisms when decomposing organic matter \u2014 a higher BOD indicates more pollution.", "difficulty": "medium", "source": "PHE \u2014 Sewage Treatment"},
        {"question": "Daily water supply requirement per head for residential quarters on Indian Railways?", "options": ["100 Litres", "135 Litres", "200 Litres", "250 Litres"], "correct": 2, "explanation": "IRWM specifies 200 litres per capita per day (lpcd) for residential areas.", "difficulty": "easy", "source": "IRWM \u2014 Water Supply"},
        {"question": "Design water allocation for non-residential passengers at railway stations?", "options": ["15 lpd", "25 lpd", "35 lpd", "45 lpd"], "correct": 1, "explanation": "For non-residential passengers, design allocation is 25 litres per person per day.", "difficulty": "easy", "source": "IRWM \u2014 Water Supply"},
        {"question": "Where are air valves positioned in a water pipeline?", "options": ["At low depressions", "At horizontal bends", "At structural summits (high points)", "At the pump house"], "correct": 2, "explanation": "Air valves at high points (summits) automatically release trapped air that reduces flow efficiency.", "difficulty": "easy", "source": "IRWM \u2014 Water Distribution"},
        {"question": "Where are scour valves (blow-off valves) installed in a water pipeline?", "options": ["At the highest points (summits)", "At the lowest depressions", "Near the pump house", "At the water treatment plant"], "correct": 1, "explanation": "Scour valves at low points and dead ends allow removal of sediment and draining for maintenance.", "difficulty": "easy", "source": "IRWM \u2014 Water Distribution"},
        {"question": "Minimum Residual Chlorine required at the farthest point of water supply network?", "options": ["0.0 mg/l", "0.1 mg/l", "0.2 mg/l", "1.0 mg/l"], "correct": 2, "explanation": "IS 10500: free residual chlorine of at least 0.2 mg/l must be maintained throughout distribution system.", "difficulty": "easy", "source": "IS 10500 \u2014 Drinking Water"},
        {"question": "Colorimetric field test to check residual chlorine:", "options": ["Phenolphthalein test", "Orthotolidine (OT) test", "Alkalinity test", "pH test"], "correct": 1, "explanation": "OT test: orthotolidine reacts with chlorine to produce yellow-brown colour indicating chlorine concentration.", "difficulty": "medium", "source": "Water Quality Testing"},
        {"question": "Acceptable pH range for drinking water (IS 10500/BIS):", "options": ["4.5 to 6.5", "6.5 to 8.5", "7.0 to 9.0", "8.0 to 10.0"], "correct": 1, "explanation": "BIS/IS 10500 specifies desirable pH range of 6.5 to 8.5 for drinking water.", "difficulty": "easy", "source": "IS 10500 \u2014 Drinking Water"},
        {"question": "Percentage of water supplied that reaches sewer as sewage:", "options": ["50%", "60%", "70%", "80%"], "correct": 3, "explanation": "Standard assumption: 80% of water supplied returns as sewage (losses from consumption, evaporation, leakage).", "difficulty": "easy", "source": "PHE \u2014 Sewerage Design"},
        {"question": "Minimum self-cleaning velocity in sanitary sewers:", "options": ["0.3 m/s", "0.6 m/s", "1.0 m/s", "1.5 m/s"], "correct": 1, "explanation": "Self-cleansing velocity of at least 0.6 m/s prevents settlement and deposition of solids in sewers.", "difficulty": "easy", "source": "PHE \u2014 Sewer Design"},
        {"question": "Maximum permissible velocity in sewers to prevent scouring:", "options": ["1.0 m/s", "1.5 m/s", "2.0 m/s", "3.0 m/s"], "correct": 2, "explanation": "Maximum design velocity in sewers limited to 2.0 m/s to prevent scouring of pipe material.", "difficulty": "medium", "source": "PHE \u2014 Sewer Design"},
        {"question": "Minimum inside diameter for a public sewer in plain areas:", "options": ["100 mm", "150 mm", "200 mm", "250 mm"], "correct": 2, "explanation": "Minimum diameter for public sewer is 200 mm to prevent clogging and allow maintenance.", "difficulty": "easy", "source": "PHE \u2014 Sewer Design"},
        {"question": "Filtration rate for Slow Sand Filters:", "options": ["100 to 200 l/m\u00b2/hr", "500 to 1000 l/m\u00b2/hr", "2000 to 3000 l/m\u00b2/hr", "3000 to 6000 l/m\u00b2/hr"], "correct": 0, "explanation": "Slow sand filters operate at low rate of 100\u2013200 litres/hour/m\u00b2 of filter area.", "difficulty": "medium", "source": "PHE \u2014 Water Treatment"},
        {"question": "Filtration rate for Rapid Sand Filters:", "options": ["100 to 200 l/m\u00b2/hr", "500 to 1000 l/m\u00b2/hr", "2000 to 3000 l/m\u00b2/hr", "3000 to 6000 l/m\u00b2/hr"], "correct": 3, "explanation": "Rapid sand filters operate at 3000\u20136000 litres/hour/m\u00b2, much higher than slow sand filters.", "difficulty": "medium", "source": "PHE \u2014 Water Treatment"},
        {"question": "Available chlorine content in commercial bleaching powder:", "options": ["10% to 15%", "20% to 25%", "30% to 35%", "40% to 45%"], "correct": 2, "explanation": "Bleaching powder used for water disinfection contains approximately 30\u201335% available chlorine.", "difficulty": "easy", "source": "PHE \u2014 Disinfection"},
        {"question": "Time for heating a public tap mouth before collecting a water sample for bacteriological analysis:", "options": ["1 minute", "2 minutes", "3 minutes", "5 minutes"], "correct": 3, "explanation": "Tap mouth must be flamed for ~5 minutes to sterilise it and eliminate surface contaminants before sampling.", "difficulty": "medium", "source": "PHE \u2014 Water Sampling"},
        {"question": "Chamber on a sewer line for inspection and cleaning:", "options": ["Catchpit", "Manhole", "Sump", "Inspection Chamber"], "correct": 1, "explanation": "A manhole provides access for inspection, maintenance, cleaning, and testing of sewer system.", "difficulty": "easy", "source": "PHE \u2014 Sewerage"},
        {"question": "Trap provided to collect sullage from bathrooms and kitchens:", "options": ["Gully trap", "Intercepting trap", "Floor trap (Nahni trap)", "P-trap"], "correct": 2, "explanation": "Floor trap (Nahni trap) collects wastewater from floors while water seal prevents foul gases entering.", "difficulty": "easy", "source": "PHE \u2014 Sanitary Fittings"},
        {"question": "Desired pH for effective disinfection by chlorination:", "options": ["pH > 8", "pH = 7", "pH < 7", "pH > 10"], "correct": 2, "explanation": "Chlorine most effective at pH < 7 as HOCl (hypochlorous acid) dominates \u2014 stronger disinfectant than OCl\u207b.", "difficulty": "medium", "source": "PHE \u2014 Disinfection"},
        {"question": "Maximum permissible cleaning interval for a septic tank:", "options": ["6 months", "12 months", "24 months", "36 months"], "correct": 1, "explanation": "Septic tanks should be cleaned at least once a year to remove accumulated sludge and scum.", "difficulty": "easy", "source": "PHE \u2014 Septic Tanks"},
        {"question": "Field test to verify the safe yield of an open well:", "options": ["Permeability test", "Recuperation test", "Pumping test", "Infiltration test"], "correct": 1, "explanation": "Recuperation test: pump well down, measure rate of water level recovery to calculate safe yield.", "difficulty": "medium", "source": "PHE \u2014 Well Hydraulics"},
        {"question": "Suspended impurities in water cause which physical characteristic?", "options": ["Color", "Taste", "Odor", "Turbidity"], "correct": 3, "explanation": "Turbidity caused by suspended particles (silt, clay, organic matter) that scatter light \u2014 cloudy appearance.", "difficulty": "easy", "source": "PHE \u2014 Water Quality"},
        {"question": "Category of impurities that act as source of water-borne diseases:", "options": ["Suspended impurities", "Dissolved impurities", "Colloidal impurities / Pathogenic bacteria", "Color-causing impurities"], "correct": 2, "explanation": "Pathogenic bacteria and viruses (colloidal size) are responsible for water-borne diseases like cholera, typhoid.", "difficulty": "easy", "source": "PHE \u2014 Water Quality"},
        {"question": "Type of hardness caused by sulfates and chlorides of Ca and Mg:", "options": ["Temporary Hardness", "Carbonate Hardness", "Permanent Hardness", "Alkaline Hardness"], "correct": 2, "explanation": "Permanent hardness (non-carbonate) caused by chlorides and sulfates of Ca/Mg \u2014 cannot be removed by boiling.", "difficulty": "easy", "source": "PHE \u2014 Water Hardness"},
        {"question": "Type of hardness caused by carbonates and bicarbonates of Ca and Mg:", "options": ["Permanent Hardness", "Temporary Hardness", "Non-Carbonate Hardness", "Sulfate Hardness"], "correct": 1, "explanation": "Temporary hardness (carbonate hardness) from dissolved bicarbonates \u2014 can be removed by boiling.", "difficulty": "easy", "source": "PHE \u2014 Water Hardness"},
        {"question": "Water softening processes for removing permanent hardness:", "options": ["Aeration and Filtration", "Chlorination and Ozonation", "Lime-Soda and Base-Exchange (Zeolite) Process", "Sedimentation and Coagulation"], "correct": 2, "explanation": "Lime-Soda process uses chemical precipitation; Zeolite/Base-Exchange uses ion-exchange to remove Ca/Mg.", "difficulty": "medium", "source": "PHE \u2014 Water Softening"},
        {"question": "Standard conditions for BOD test:", "options": ["1 day at 27\u00b0C", "3 days at 25\u00b0C", "5 days at 20\u00b0C", "10 days at 15\u00b0C"], "correct": 2, "explanation": "Standard BOD\u2085 test: 5 days at 20\u00b0C in the dark (incubation period and temperature standardised globally).", "difficulty": "easy", "source": "PHE \u2014 Sewage Analysis"},
        {"question": "Rapid methods for testing a sewer for leaks and blockages before commissioning:", "options": ["Pressure test, Vacuum test", "Air test, Water test, Smoke test", "Dye test, Sonic test", "Hydrostatic test, Chemical test"], "correct": 1, "explanation": "Before commissioning: air test (integrity), water test (leaks), smoke test (detect defects/illegal connections).", "difficulty": "medium", "source": "PHE \u2014 Sewer Testing"},
        {"question": "Comparison of COD and BOD for the same wastewater sample:", "options": ["COD < BOD", "COD = BOD", "COD > BOD", "No fixed relationship"], "correct": 2, "explanation": "COD measures oxygen to oxidize all organic matter (biodegradable + non-biodegradable); COD \u2265 BOD always.", "difficulty": "medium", "source": "PHE \u2014 Sewage Analysis"},
        {"question": "Standard slope provided for bathroom floors towards the outlet:", "options": ["1 in 20", "1 in 40", "1 in 60", "1 in 100"], "correct": 2, "explanation": "Bathroom floors sloped at 1 in 60 towards floor trap \u2014 ensures drainage without uncomfortably steep slope.", "difficulty": "easy", "source": "IRWM \u2014 Building Services"},
        {"question": "Standard slope for passenger platform surfaces on Indian Railways:", "options": ["1 in 20", "1 in 40", "1 in 60", "1 in 100"], "correct": 2, "explanation": "Railway platforms sloped at 1 in 60 so rainwater drains quickly without pooling.", "difficulty": "medium", "source": "IRWM \u2014 Platform Construction"},
        {"question": "Purpose of providing water-sealed traps in sanitary pipe layout:", "options": ["Allow air to enter the pipe", "Prevent entry of foul sewer gases into buildings", "Increase flow velocity", "Reduce noise in pipes"], "correct": 1, "explanation": "Water seal trap retains water in pipe bend creating barrier preventing foul gases and insects entering buildings.", "difficulty": "easy", "source": "PHE \u2014 Sanitary Plumbing"},
        {"question": "Maximum allowable turbidity for drinking water (IRWM/IS 10500)?", "options": ["1 NTU", "5 NTU", "10 NTU", "15 NTU"], "correct": 2, "explanation": "IRWM and IS 10500 specify turbidity should not exceed 10 NTU for drinking water.", "difficulty": "easy", "source": "IS 10500 / IRWM"},
        {"question": "Minimum depth of water seal required in a sanitary trap:", "options": ["25 mm", "50 mm", "75 mm", "100 mm"], "correct": 1, "explanation": "Minimum 50 mm water seal depth is standard for sanitary traps \u2014 effective barrier against foul gases.", "difficulty": "easy", "source": "PHE \u2014 Sanitary Fittings"},
        {"question": "Pump type selected for tube wells with a small discharge diameter:", "options": ["Centrifugal pump", "Jet pump", "Reciprocating pump", "Submersible pump"], "correct": 3, "explanation": "Submersible pumps placed directly inside the well are most efficient for small-diameter tube wells.", "difficulty": "easy", "source": "PHE \u2014 Water Supply"},
        {"question": "Class of bacteria that decomposes sludge in an anaerobic septic tank:", "options": ["Aerobic bacteria", "Facultative bacteria", "Anaerobic bacteria", "Thermo-tolerant bacteria"], "correct": 2, "explanation": "Septic tank is anaerobic (no oxygen); anaerobic bacteria decompose sludge into gases, liquids, and stable matter.", "difficulty": "easy", "source": "PHE \u2014 Sewage Treatment"},
    ],
    "ConstructionMat": [
        {"question": "Initial setting time of Ordinary Portland Cement (OPC) should NOT be less than ___", "options": ["15 minutes", "30 minutes", "45 minutes", "60 minutes"], "correct": 1, "explanation": "As per IS 269, the initial setting time of OPC should not be less than 30 minutes. This allows sufficient time for mixing, transporting and placing.", "difficulty": "easy", "source": "IS 269 \u2014 Cement Standards"},
        {"question": "The specific gravity of OPC (Ordinary Portland Cement) is approximately ___", "options": ["2.5", "3.15", "2.8", "3.5"], "correct": 1, "explanation": "The specific gravity of Ordinary Portland Cement is approximately 3.15, used in mix design calculations.", "difficulty": "easy", "source": "Concrete Technology \u2014 Cement Properties"},
        {"question": "Seasoning of timber is done to ___", "options": ["Increase its weight", "Reduce moisture content to prevent warping, cracking and decay", "Improve its color", "Increase its density"], "correct": 1, "explanation": "Seasoning removes excess moisture from timber to prevent warping, shrinkage, cracking, and decay during service.", "difficulty": "easy", "source": "Construction Materials \u2014 Timber"},
        {"question": "The IS code for classification of Indian timber is ___", "options": ["IS 399", "IS 456", "IS 800", "IS 2720"], "correct": 0, "explanation": "IS 399 classifies commercial Indian timbers and provides their physical and mechanical properties for structural use.", "difficulty": "hard", "source": "IS 399 \u2014 Timber Classification"},
    ],
    "Hydraulics": [
        {"question": "Froude number is the ratio of ___", "options": ["Inertia force to viscous force", "Inertia force to gravity force", "Pressure force to inertia force", "Viscous force to gravity force"], "correct": 1, "explanation": "Froude number (Fr) = V/\u221a(gL) represents the ratio of inertial forces to gravitational forces. Fr<1 is subcritical, Fr>1 is supercritical flow.", "difficulty": "medium", "source": "Hydraulics \u2014 Open Channel Flow"},
        {"question": "The formula for discharge over a rectangular sharp-crested weir (without end contractions) is ___", "options": ["Q = 1.84 L H^(3/2)", "Q = 1.71 L H", "Q = 2.23 L H^(5/2)", "Q = 0.61 \u00d7 L \u00d7 H \u00d7 \u221a(2gH)"], "correct": 0, "explanation": "Francis' formula: Q = 1.84 L H^(3/2) (SI units) for discharge over a rectangular sharp-crested weir where L = length, H = head of water.", "difficulty": "medium", "source": "Hydraulics \u2014 Weirs"},
        {"question": "Manning's formula for flow velocity in open channels is ___", "options": ["V = C\u221a(RS)", "V = (1/n) R^(2/3) S^(1/2)", "V = K \u00d7 i \u00d7 A", "V = Q/A"], "correct": 1, "explanation": "Manning's formula: V = (1/n) \u00d7 R^(2/3) \u00d7 S^(1/2), where n = Manning's roughness coefficient, R = hydraulic radius, S = slope.", "difficulty": "medium", "source": "Hydraulics \u2014 Manning's Formula"},
        {"question": "The return period of a design flood for a major bridge on Indian Railways is generally taken as ___", "options": ["25 years", "50 years", "100 years", "500 years"], "correct": 2, "explanation": "Design floods for major railway bridges are typically based on a 100-year return period flood to ensure adequate safety.", "difficulty": "medium", "source": "Hydrology \u2014 Design Flood"},
        {"question": "Froude Number for critical flow in an open channel:", "options": ["Less than 1", "Equal to 1", "Greater than 1", "Zero"], "correct": 1, "explanation": "Critical flow (minimum specific energy for given discharge) is characterised by Froude number = 1.", "difficulty": "easy", "source": "Hydraulics \u2014 Open Channel Flow"},
        {"question": "Definition of Hydraulic Radius in an open channel:", "options": ["Wetted Area / Top Width", "Wetted Area / Wetted Perimeter", "Top Width / Wetted Area", "Wetted Perimeter / Wetted Area"], "correct": 1, "explanation": "Hydraulic radius R = Cross-sectional area / Wetted perimeter, key parameter in Manning's equation.", "difficulty": "easy", "source": "Hydraulics \u2014 Manning's Equation"},
        {"question": "Definition of Hydraulic Depth in an open channel:", "options": ["Wetted Area / Wetted Perimeter", "Top Width / Wetted Area", "Wetted Area / Top Width", "Wetted Perimeter / Top Width"], "correct": 2, "explanation": "Hydraulic depth D = Cross-sectional flow area / Top width of water surface.", "difficulty": "medium", "source": "Hydraulics \u2014 Open Channel Flow"},
        {"question": "Froude Number for super-critical flow:", "options": ["Fr < 1", "Fr = 1", "Fr > 1", "Fr = 0"], "correct": 2, "explanation": "Supercritical flow is high-velocity shallow flow where Froude number > 1.", "difficulty": "easy", "source": "Hydraulics \u2014 Flow Regimes"},
        {"question": "Froude Number for sub-critical flow:", "options": ["Fr < 1", "Fr = 1", "Fr > 1", "Fr = 0"], "correct": 0, "explanation": "Subcritical flow is tranquil, low-velocity flow where Froude number < 1.", "difficulty": "easy", "source": "Hydraulics \u2014 Flow Regimes"},
        {"question": "A sudden rise in water level when flow changes from super-critical to sub-critical:", "options": ["Standing wave", "Undular jump", "Critical hump", "Hydraulic jump"], "correct": 3, "explanation": "Hydraulic jump: high-velocity supercritical flow abruptly changes to low-velocity subcritical flow, dissipating energy.", "difficulty": "medium", "source": "Hydraulics \u2014 Hydraulic Jump"},
        {"question": "Condition for the most economical rectangular channel:", "options": ["Bottom width = Depth of flow", "Bottom width = 1.5 \u00d7 Depth", "Bottom width = 2 \u00d7 Depth", "Bottom width = 3 \u00d7 Depth"], "correct": 2, "explanation": "For hydraulically efficient rectangular channel (minimum wetted perimeter), bottom width b = 2 \u00d7 depth d.", "difficulty": "medium", "source": "Hydraulics \u2014 Channel Design"},
        {"question": "Graph showing river discharge vs. time is called:", "options": ["Hyetograph", "Duration Curve", "Flow Duration Curve", "Hydrograph"], "correct": 3, "explanation": "A hydrograph plots discharge of a river over time, typically in response to a rainfall event.", "difficulty": "easy", "source": "Hydrology \u2014 Hydrograph"},
        {"question": "X-axis coordinate in a standard hydrograph:", "options": ["Discharge", "Velocity", "Time", "Stage"], "correct": 2, "explanation": "In a hydrograph, time (hours or days) is plotted on X-axis and corresponding discharge on Y-axis.", "difficulty": "easy", "source": "Hydrology \u2014 Hydrograph"},
        {"question": "Empirical formula for flood discharge in North and Central India:", "options": ["Ryves Formula", "Dicken's Formula", "Inglis Formula", "Fuller's Formula"], "correct": 1, "explanation": "Dicken's Formula Q = C \u00d7 A^(3/4) is used for estimating flood discharge in North and Central India.", "difficulty": "medium", "source": "Hydrology \u2014 Flood Formulae"},
        {"question": "Empirical formula for flood discharge in South India:", "options": ["Dicken's Formula", "Ryves Formula", "Inglis Formula", "Fuller's Formula"], "correct": 1, "explanation": "Ryves Formula Q = C \u00d7 A^(2/3) is adopted for flood estimation in southern India.", "difficulty": "medium", "source": "Hydrology \u2014 Flood Formulae"},
        {"question": "Which drainage basin shape produces a larger peak runoff?", "options": ["Fern-shaped", "Fan-shaped", "Elongated", "Radial"], "correct": 1, "explanation": "Fan-shaped basin: runoff from all parts converges at outlet simultaneously \u2014 higher peak discharge.", "difficulty": "medium", "source": "Hydrology \u2014 Basin Shape"},
        {"question": "Fluid property that offers resistance to shear stress:", "options": ["Density", "Surface Tension", "Viscosity", "Compressibility"], "correct": 2, "explanation": "Viscosity is the measure of a fluid's resistance to shear stress \u2014 its internal friction.", "difficulty": "easy", "source": "Fluid Mechanics \u2014 Properties"},
        {"question": "Effect of temperature increase on dynamic viscosity of liquids:", "options": ["Increases", "Decreases", "Remains unchanged", "First increases then decreases"], "correct": 1, "explanation": "For liquids, increased temperature lowers intermolecular cohesive forces \u2192 viscosity decreases.", "difficulty": "easy", "source": "Fluid Mechanics \u2014 Viscosity"},
        {"question": "Effect of temperature increase on dynamic viscosity of gases:", "options": ["Increases", "Decreases", "Remains unchanged", "First decreases then increases"], "correct": 0, "explanation": "In gases, viscosity arises from molecular momentum transfer; more collisions at higher temperature \u2192 viscosity increases.", "difficulty": "medium", "source": "Fluid Mechanics \u2014 Viscosity"},
        {"question": "Definition of an Ideal Fluid:", "options": ["Zero viscosity and incompressible", "High viscosity and compressible", "Zero surface tension", "High density"], "correct": 0, "explanation": "An ideal fluid is theoretical: zero viscosity (inviscid) and incompressible.", "difficulty": "easy", "source": "Fluid Mechanics \u2014 Ideal Fluid"},
        {"question": "Condition for laminar flow in a pipe (Reynolds Number):", "options": ["Re > 4000", "Re between 2000 and 4000", "Re < 2000", "Re = 1"], "correct": 2, "explanation": "Flow is laminar when Re < 2000; viscous forces dominate and layers flow in parallel.", "difficulty": "easy", "source": "Fluid Mechanics \u2014 Reynolds Number"},
        {"question": "Condition for steady flow:", "options": ["Quantity varies with time", "Velocity varies with time", "Quantity flowing per second is constant over time", "Depth of flow varies"], "correct": 2, "explanation": "Steady flow: mass/volumetric flow rate past any point is constant with respect to time.", "difficulty": "easy", "source": "Fluid Mechanics \u2014 Flow Classification"},
        {"question": "Definition of a Prismatic Channel:", "options": ["Constant bed slope and constant cross-section", "Channel with varying bed slope", "Constant cross-section but varying slope", "A natural stream channel"], "correct": 0, "explanation": "A prismatic channel has constant shape, size, and bed slope along its length.", "difficulty": "easy", "source": "Hydraulics \u2014 Channel Types"},
        {"question": "Formula for Specific Energy (E) in an open channel:", "options": ["E = z + V\u00b2/2g", "E = y + V\u00b2/2g", "E = z + y", "E = V\u00b2/2g"], "correct": 1, "explanation": "Specific energy E = y + V\u00b2/2g (depth + velocity head, relative to channel bottom).", "difficulty": "medium", "source": "Hydraulics \u2014 Specific Energy"},
        {"question": "Definition of Critical Depth in open channels:", "options": ["Depth at which velocity is maximum", "Depth at which specific energy is minimum for a given discharge", "Depth at which Froude number is zero", "Depth at which discharge is minimum"], "correct": 1, "explanation": "Critical depth yc: depth of flow at which specific energy is minimum for a given discharge.", "difficulty": "medium", "source": "Hydraulics \u2014 Critical Flow"},
        {"question": "The rise in water level upstream of a bridge is called:", "options": ["Head loss", "Afflux", "Drawdown", "Depression"], "correct": 1, "explanation": "Afflux: increase in water level upstream caused by constriction of river at bridge opening.", "difficulty": "easy", "source": "IRBM \u2014 Bridge Hydraulics"},
        {"question": "Maximum permissible design afflux on Indian Railways?", "options": ["50 mm", "100 mm", "150 mm", "300 mm"], "correct": 2, "explanation": "Indian Railways Bridge Manual restricts permissible afflux to 150 mm for bridge structures.", "difficulty": "medium", "source": "IRBM \u2014 Bridge Hydraulics"},
        {"question": "Instrument used to measure stream flow velocity:", "options": ["Anemometer", "Current Meter", "Pyrometer", "Hygrometer"], "correct": 1, "explanation": "A current meter measures velocity of flow in open channels and streams.", "difficulty": "easy", "source": "Hydrology \u2014 Flow Measurement"},
        {"question": "Flood frequency for major bridge design on Indian Railways:", "options": ["25-year", "50-year", "100-year", "500-year"], "correct": 1, "explanation": "Per IRBM Para 2.2, major bridges are designed for 50-year return period flood.", "difficulty": "medium", "source": "IRBM \u2014 Para 2.2"},
        {"question": "Percentage increase in design flood discharge for small catchments (< 500 sq. km):", "options": ["10%", "20%", "30%", "50%"], "correct": 2, "explanation": "A 30% increase is applied to calculated design discharge for small catchments as a safety margin.", "difficulty": "medium", "source": "IRBM \u2014 Flood Discharge"},
        {"question": "Low walls at bridge entry and exit to reduce scouring are:", "options": ["Retaining walls", "Breast walls", "Drop wall and Curtain wall", "Parapet walls"], "correct": 2, "explanation": "Drop walls break the fall of water at inlet; curtain walls at outlet extend deep to prevent scour.", "difficulty": "easy", "source": "IRBM \u2014 Bridge Protection Works"},
        {"question": "Law for determining water flow velocity through an aquifer:", "options": ["Manning's Law", "Chezy's Law", "Darcy's Law", "Lacey's Law"], "correct": 2, "explanation": "Darcy's Law: flow rate through porous medium is proportional to hydraulic gradient and permeability.", "difficulty": "easy", "source": "Hydrology \u2014 Groundwater"},
        {"question": "According to Lacey's regime theory, the silt factor is directly proportional to:", "options": ["Average particle size", "Square root of average particle size", "Cube of average particle size", "Square of average particle size"], "correct": 1, "explanation": "Lacey's silt factor f \u221d \u221ad (square root of average particle size d).", "difficulty": "medium", "source": "Hydraulics \u2014 Lacey's Theory"},
        {"question": "'Piping' in hydraulic structures refers to:", "options": ["Erosion by flowing water", "Boiling of sand due to upward seepage", "Cavitation", "Scour due to waves"], "correct": 1, "explanation": "Piping: upward seepage forces reduce effective stress, causing sand to boil and flow \u2014 progressive erosion.", "difficulty": "medium", "source": "Hydraulics \u2014 Seepage"},
    ],
    "Miscellaneous": [
        {"question": "The speed restriction imposed on a railway track after deep screening of ballast is ___", "options": ["No restriction", "Engineering speed (30 kmph)", "50 kmph for one week", "30 kmph until consolidation"], "correct": 3, "explanation": "After deep screening, a 30 kmph speed restriction is imposed until adequate consolidation under traffic is achieved and track geometry stabilizes.", "difficulty": "medium", "source": "IRPWM \u2014 Post-Maintenance Restrictions"},
        {"question": "G&SR stands for ___", "options": ["General and Subsidiary Rules", "General and Special Rules", "Guide and Safety Rules", "Gauge and Standard Rules"], "correct": 0, "explanation": "G&SR (General and Subsidiary Rules) are rules framed under the Railway Act governing the working of trains, signals, and safety on Indian Railways.", "difficulty": "easy", "source": "G&SR \u2014 Introduction"},
        {"question": "Block working in railways refers to ___", "options": ["A method of working where only one train occupies a block section at a time", "Working of freight trains only", "The maintenance block for track works", "Working with token instruments only"], "correct": 0, "explanation": "Block system ensures only one train at a time is allowed in a block section (between two block stations), providing basic safety against collision.", "difficulty": "easy", "source": "G&SR \u2014 Block Working"},
        {"question": "The authority for a train to enter a block section is ___", "options": ["Driver's own judgment", "Line Clear token/authority given by Station Master", "Speed certificate", "Loco pilot's order"], "correct": 1, "explanation": "A train can enter a block section only after obtaining a Line Clear token/authority from the station master, ensuring the section is clear.", "difficulty": "easy", "source": "G&SR \u2014 Train Working"},
        {"question": "Works requiring temporary single line working (TSL) need a sanction from ___", "options": ["SSE/P.Way", "ADEN", "Divisional Engineer", "General Manager"], "correct": 2, "explanation": "Temporary Single Line working affecting train operations requires sanction of the Divisional Engineer (DE/AEN in coordination with DEN).", "difficulty": "medium", "source": "IRPWM / G&SR \u2014 TSL"},
        {"question": "As per G&SR, the maximum speed over a temporary speed restriction (TSR) imposed by engineering department is ___", "options": ["15 kmph", "30 kmph", "As specified in the TSR notice", "50 kmph"], "correct": 2, "explanation": "The speed of TSR is specified in the Engineering Speed Restriction notice issued by the SE/SSE and published in the Special Train Notice.", "difficulty": "medium", "source": "G&SR \u2014 Speed Restrictions"},
        {"question": "An Engineering Caution Order is given to the driver ___", "options": ["For every train", "When speed restriction is imposed over 15 kmph", "When speed restriction is 15 kmph or below", "Only for goods trains"], "correct": 2, "explanation": "A written Caution Order (CA) is given to the driver at the station preceding the restriction point when the restricted speed is 15 kmph or below.", "difficulty": "medium", "source": "G&SR \u2014 Caution Orders"},
        {"question": "A 'Fit to run certificate' for OHE (Overhead Equipment) maintenance is given by ___", "options": ["TRD (Traction) Department", "Civil Engineering", "Signal Department", "Mechanical Department"], "correct": 0, "explanation": "Fit-to-run (resumption of traffic) after OHE maintenance work is certified by TRD (Traction-Electrical) Department officer.", "difficulty": "easy", "source": "G&SR \u2014 Departmental Responsibilities"},
        {"question": "The correct sequence of shunting movements at a station is ___", "options": ["Signal \u2192 Move \u2192 Brake", "Point \u2192 Signal \u2192 Move", "Check line clear \u2192 Set points \u2192 Signal \u2192 Move", "Move \u2192 Check points \u2192 Stop"], "correct": 2, "explanation": "Safe shunting sequence: verify line is clear, set/check points correctly, obtain signal authority, then move the vehicles.", "difficulty": "medium", "source": "G&SR \u2014 Shunting Rules"},
        {"question": "Trolley refuge is provided near tracks to ___", "options": ["Store maintenance tools", "Provide shelter for track men in case of approaching trains", "Store materials for emergency", "Park trolleys at night"], "correct": 1, "explanation": "Trolley refuges are small shelters built adjacent to the track at regular intervals where track-men and trolleys can take shelter when trains approach.", "difficulty": "easy", "source": "IRPWM \u2014 Safety Measures"},
        {"question": "The detonators in railways are used as ___", "options": ["Explosive devices for demolition", "Warning signals to alert drivers of danger ahead", "Fog signals only", "To mark kilometer posts"], "correct": 1, "explanation": "Detonators (fog signals) are placed on rails to give an audible warning to loco pilots by exploding under wheel pressure, alerting them to danger ahead.", "difficulty": "easy", "source": "G&SR \u2014 Fog Signals"},
        {"question": "As per IRPWM, the gang patrolman (track watchman) should patrol his beat ___", "options": ["Only during fog and heavy rain", "During night only", "Continuously, especially during vulnerable seasons", "Only during monsoon"], "correct": 2, "explanation": "Gang patrolmen continuously patrol their assigned beats, with increased vigilance during monsoon, fog, and after heavy rains to detect track damage.", "difficulty": "easy", "source": "IRPWM \u2014 Track Patrolling"},
        {"question": "Which document records the details of all trains running on a railway section?", "options": ["Train graph", "Control chart", "Running room register", "Train passing register"], "correct": 0, "explanation": "A train graph (or train working graph) is a graphical representation of all trains scheduled on a section, showing their movements against time.", "difficulty": "medium", "source": "G&SR \u2014 Train Working Documents"},
    ],
}

# ── Main Knowledge Panel ───────────────────────────────────────────────────────
class KnowledgePanel(QWidget):
    def __init__(self):
        super().__init__()
        self.settings       = QSettings("BES", "BridgeEngineeringSuite")
        self._questions     = []
        self._q_index       = 0
        self._score         = 0
        self._answered      = False
        self._search_results= []
        self._quiz_worker   = None
        self._search_worker = None
        # Font size for question text (default 14pt)
        self._q_font_size   = int(self.settings.value("q_font_size", 14))
        # Theme: "dark" or "light"
        self._theme         = self.settings.value("ui_theme", "dark")
        self._build()

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _gemini_key(self) -> str:
        """Return Gemini API key from settings or environment."""
        return (self.settings.value("gemini_api_key", "") or
                os.environ.get("GEMINI_API_KEY", ""))

    def _claude_key(self) -> str:
        """Return Claude/Anthropic API key from settings or environment."""
        return (self.settings.value("claude_api_key", "") or
                # legacy single-key setting kept for migration
                self.settings.value("api_key", "") or
                os.environ.get("ANTHROPIC_API_KEY", ""))

    def _api_key(self) -> str:
        """
        Return whichever key is available (Gemini preferred).
        Kept for backward-compat with callers that only need one key string.
        """
        return self._gemini_key() or self._claude_key()

    def _ai_provider(self) -> str:
        """
        Return 'dual' sentinel when both (or either) key is present so callers
        know to use AIProvider.dual().  Falls back to detect_provider for the
        legacy single-key path.
        """
        gk = self._gemini_key()
        ck = self._claude_key()
        if gk or ck:
            return "__dual__"
        return detect_provider(self._api_key())

    def _make_ai(self) -> "AIProvider":
        """
        Construct the right AIProvider for the current key configuration.
        • Both keys → dual-mode (Gemini-first, Claude-fallback)
        • Only Gemini key → Gemini only
        • Only Claude key → Claude only
        """
        gk = self._gemini_key()
        ck = self._claude_key()
        if gk and ck:
            return AIProvider.dual(gk, ck)
        if gk:
            return AIProvider(gk, PROVIDER_GEMINI)
        return AIProvider(ck, PROVIDER_ANTHROPIC)

    def _section_card(self, title, subtitle=""):
        frame = QFrame(); frame.setObjectName("card")
        layout = QVBoxLayout(frame); layout.setContentsMargins(20, 16, 20, 16); layout.setSpacing(6)
        t = QLabel(title); t.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        t.setStyleSheet(f"color:{COLORS['text_primary']};")
        layout.addWidget(t)
        if subtitle:
            s = QLabel(subtitle); s.setWordWrap(True)
            s.setStyleSheet(f"color:{COLORS['text_secondary']};font-size:12px;")
            layout.addWidget(s)
        return frame, layout

    def _make_opt_btn(self, label):
        btn = QPushButton(label)
        btn.setObjectName("secondaryBtn")
        btn.setMinimumHeight(44)
        btn.setFont(QFont("Segoe UI", 13))
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['input_bg']};
                border: 1.5px solid {COLORS['border']};
                border-radius: 8px;
                padding: 8px 16px;
                text-align: left;
                font-size: 17px;
                color: {COLORS['text_primary']};
            }}
            QPushButton:hover {{
                background: {COLORS['hover_bg']};
                border-color: {COLORS['accent']};
            }}
            QPushButton:disabled {{
                opacity: 0.85;
            }}
        """)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    # ── UI Build ──────────────────────────────────────────────────────────────
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(32, 28, 32, 32)
        layout.setSpacing(20)
        scroll.setWidget(container)
        outer.addWidget(scroll)

        layout.addWidget(self._kb_hero())

        tools_card = QFrame(); tools_card.setObjectName("card")
        tools_layout = QVBoxLayout(tools_card)
        tools_layout.setContentsMargins(20, 18, 20, 18)
        tools_layout.setSpacing(10)
        header = QLabel("Tools")
        header.setObjectName("sectionHeader")
        tools_layout.addWidget(header)

        # Build every section once (unchanged internally) so all cross-referenced
        # widgets/attributes exist — e.g. the search index builder reads
        # self.topic_combo from the quiz section. Each section then lives in its
        # own resizable dialog instead of being crammed onto one fixed-size page,
        # which is what caused the overlap on smaller screens.
        quiz_frame = self._build_quiz_section()
        import_frame = self._build_import_section()
        search_frame = self._build_search_section()

        self._quiz_dialog = self._make_tool_dialog("Quiz Section", quiz_frame, 1180, 760)
        self._import_dialog = self._make_tool_dialog("Import Questions from File", import_frame, 900, 640)
        self._search_dialog = self._make_tool_dialog("Code & Manual Search Engine", search_frame, 1180, 760)

        tools_layout.addWidget(self._tool_card(
            "quiz", "Quiz Section",
            "Practice LDCE-pattern questions with instant scoring.", self._quiz_dialog))
        tools_layout.addWidget(self._tool_card(
            "import", "Import Questions from File",
            "Add new questions to the local bank from a file.", self._import_dialog))
        tools_layout.addWidget(self._tool_card(
            "codesearch", "Code & Manual Search Engine",
            "Search indexed manuals and codes by keyword.", self._search_dialog))

        layout.addWidget(tools_card)
        layout.addStretch()

    def _kb_hero(self) -> QFrame:
        hero = QFrame()
        hero.setObjectName("heroBanner")
        lay = QVBoxLayout(hero)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(6)

        kicker = QLabel("KNOWLEDGE BASE")
        kicker.setObjectName("heroKicker")
        title = QLabel("LDCE Railway Exam Prep & Reference")
        title.setObjectName("heroTitle")
        title.setWordWrap(True)
        subtitle = QLabel("PYQ-based quiz practice, question bank import, and fast manual search.")
        subtitle.setObjectName("heroSubtitle")
        subtitle.setWordWrap(True)

        lay.addWidget(kicker)
        lay.addWidget(title)
        lay.addWidget(subtitle)
        return hero

    def _tool_card(self, icon_key: str, name: str, meta: str, dialog: QDialog) -> QFrame:
        card = QFrame()
        card.setObjectName("storeCard")
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(14)

        icon_lbl = QLabel()
        icon_lbl.setObjectName("storeIcon")
        icon_lbl.setFixedSize(46, 46)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        path = get_icon_path(icon_key)
        if path:
            pix = QPixmap(path).scaled(
                46, 46, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            icon_lbl.setPixmap(pix)
        row.addWidget(icon_lbl)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name_lbl = QLabel(name)
        name_lbl.setObjectName("storeAppName")
        meta_lbl = QLabel(meta)
        meta_lbl.setObjectName("storeAppMeta")
        meta_lbl.setWordWrap(True)
        text_col.addWidget(name_lbl)
        text_col.addWidget(meta_lbl)
        row.addLayout(text_col, 1)

        open_btn = QPushButton("Open")
        open_btn.setObjectName("openBtn")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.setFixedWidth(84)
        open_btn.clicked.connect(lambda: (dialog.show(), dialog.raise_(), dialog.activateWindow()))
        row.addWidget(open_btn)
        return card

    def _make_tool_dialog(self, title: str, content: QWidget, width: int, height: int) -> QDialog:
        """House one section's existing widget tree in its own resizable window,
        so it gets real estate independent of the main window's size."""
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setStyleSheet(self.window().styleSheet() if self.window() else "")
        dlg.resize(width, height)
        dlg.setMinimumSize(720, 480)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(dlg)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        lay.addWidget(scroll)
        return dlg

    # ── Quiz Section ──────────────────────────────────────────────────────────
    def _build_quiz_section(self):
        # Outer widget — scrolling is provided by the dialog that now houses this section
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(20, 14, 20, 14)
        root.setSpacing(8)

        # ── Title row ─────────────────────────────────────────────────────
        row0 = QHBoxLayout()
        title = QLabel("🎯  Quiz App")
        title.setObjectName("sectionTitle")
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        row0.addWidget(title)
        row0.addStretch()

        self.score_badge = QLabel("Score: —")
        self.score_badge.setStyleSheet(
            f"background:{COLORS['accent_glow']};color:{COLORS['accent']};"
            f"border:1px solid rgba(0,200,160,0.4);border-radius:10px;"
            f"padding:3px 12px;font-weight:600;font-size:12px;")
        row0.addWidget(self.score_badge)
        root.addLayout(row0)

        exam_info = QLabel(
            "LDCE Pattern → Part A: 85 Qs (80 marks) | Part B: 55 Qs (40 marks) | "
            "Part C: 35 Qs (30 marks)  •  −⅓ negative  •  Qualifying: 90/150"
        )
        exam_info.setStyleSheet(
            f"background:{COLORS['info_bg']};color:{COLORS['info']};"
            f"border-left:3px solid {COLORS['info']};"
            f"border-radius:4px;padding:5px 10px;font-size:10px;")
        exam_info.setWordWrap(True)
        root.addWidget(exam_info)

        # ── Controls card ─────────────────────────────────────────────────
        ctrl_frame = QFrame(); ctrl_frame.setObjectName("accentCard")
        ctrl_lay = QVBoxLayout(ctrl_frame)
        ctrl_lay.setContentsMargins(14, 10, 14, 10); ctrl_lay.setSpacing(7)

        lbl = QLabel("SELECT TOPIC"); lbl.setObjectName("fieldLabel")
        ctrl_lay.addWidget(lbl)

        sel_row = QHBoxLayout(); sel_row.setSpacing(8)
        self.topic_combo = QComboBox()
        self.topic_combo.setMinimumHeight(36)
        self.topic_combo.setStyleSheet("font-size:12px;padding:4px 8px;")
        for display, key, cnt, prio in TOPICS:
            if key == "SurpriseTest":
                self.topic_combo.addItem(f"{prio}  {display}", userData=key)
            else:
                self.topic_combo.addItem(f"{prio}  {display}  [{cnt} PYQs]", userData=key)
        sel_row.addWidget(self.topic_combo, 5)

        self.q_count_combo = QComboBox()
        self.q_count_combo.setMinimumHeight(36)
        for n in [5, 10, 15, 20, 25, 30, 40, 50]:
            self.q_count_combo.addItem(f"{n} Questions", userData=n)
        self.q_count_combo.setCurrentIndex(1)   # default 10
        sel_row.addWidget(self.q_count_combo, 1)

        self.start_btn = QPushButton("▶  Start Quiz")
        self.start_btn.setObjectName("primaryBtn")
        self.start_btn.setMinimumHeight(36)
        self.start_btn.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.start_btn.clicked.connect(self._start_quiz)
        sel_row.addWidget(self.start_btn, 2)
        ctrl_lay.addLayout(sel_row)

        self.quiz_status = QLabel(
            "Choose a topic and press Start Quiz."
        )
        self.quiz_status.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:10px;")
        ctrl_lay.addWidget(self.quiz_status)
        root.addWidget(ctrl_frame)

        # ── Progress bar ──────────────────────────────────────────────────
        self.prog_bar = QProgressBar()
        self.prog_bar.setMaximum(100); self.prog_bar.setValue(0)
        self.prog_bar.setFixedHeight(5); self.prog_bar.setTextVisible(False)
        root.addWidget(self.prog_bar)

        # ── Question card (stretch to fill remaining space) ───────────────
        self.q_card = QFrame(); self.q_card.setObjectName("accentCard")
        self.q_card.setVisible(False)
        q_lay = QVBoxLayout(self.q_card)
        q_lay.setContentsMargins(16, 12, 16, 12); q_lay.setSpacing(8)

        # Header row: Q number | difficulty | timer | Check Needed btn | font-size ctrl
        q_header = QHBoxLayout(); q_header.setSpacing(8)

        self.q_num_label = QLabel("Question 1 / 10")
        self.q_num_label.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:11px;font-weight:600;")
        q_header.addWidget(self.q_num_label)

        q_header.addStretch()

        self.diff_label = QLabel("")
        self.diff_label.setStyleSheet(
            "font-size:10px;border-radius:4px;padding:2px 6px;font-weight:600;")
        q_header.addWidget(self.diff_label)

        # 50-second countdown timer badge
        self.timer_label = QLabel("⏱ 50s")
        self.timer_label.setFixedWidth(58)
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer_label.setStyleSheet(
            f"background:{COLORS['warning_bg']};color:{COLORS['warning']};"
            f"border:1px solid {COLORS['warning']};border-radius:6px;"
            f"padding:2px 6px;font-size:11px;font-weight:700;")
        q_header.addWidget(self.timer_label)

        # Check Needed button
        self.check_btn = QPushButton("🚩 Mark for Check")
        self.check_btn.setObjectName("secondaryBtn")
        self.check_btn.setFixedHeight(28)
        self.check_btn.setStyleSheet(
            f"font-size:10px;padding:2px 8px;"
            f"background:{COLORS['warning_bg']};color:{COLORS['warning']};"
            f"border:1px solid {COLORS['warning']};border-radius:5px;")
        self.check_btn.setToolTip(
            "Mark this question as needing accuracy verification.\n"
            "Marked questions will be checked against your database or online.")
        self.check_btn.clicked.connect(self._toggle_check_flag)
        q_header.addWidget(self.check_btn)

        # ── Font-size +/- minimalist buttons ─────────────────────────────
        _fs_style = (
            f"QPushButton{{background:transparent;color:{COLORS['text_muted']};"
            f"border:1px solid {COLORS['border']};border-radius:4px;"
            f"font-size:13px;font-weight:700;padding:0px;}}"
            f"QPushButton:hover{{background:{COLORS['hover_bg']};"
            f"color:{COLORS['accent']};border-color:{COLORS['accent']};}}"
        )
        self._fs_minus_btn = QPushButton("−")
        self._fs_minus_btn.setFixedSize(22, 22)
        self._fs_minus_btn.setToolTip("Decrease question font size")
        self._fs_minus_btn.setStyleSheet(_fs_style)
        self._fs_minus_btn.clicked.connect(self._font_size_dec)
        q_header.addWidget(self._fs_minus_btn)

        self._fs_plus_btn = QPushButton("+")
        self._fs_plus_btn.setFixedSize(22, 22)
        self._fs_plus_btn.setToolTip("Increase question font size")
        self._fs_plus_btn.setStyleSheet(_fs_style)
        self._fs_plus_btn.clicked.connect(self._font_size_inc)
        q_header.addWidget(self._fs_plus_btn)

        q_lay.addLayout(q_header)

        # Question text
        self.q_text = QLabel("")
        self.q_text.setWordWrap(True)
        self.q_text.setFont(QFont("Segoe UI", 14))
        self.q_text.setStyleSheet(
            f"color:{COLORS['text_primary']};line-height:1.5;")
        self.q_text.setMinimumHeight(48)
        q_lay.addWidget(self.q_text)

        # PYQ date badge — shown only for previous year questions
        self._pyq_badge = QLabel("")
        self._pyq_badge.setVisible(False)
        self._pyq_badge.setStyleSheet(
            f"background:{COLORS.get('accent_glow','rgba(0,200,160,0.12)')};color:{COLORS['accent']};"
            f"border:1px solid {COLORS['accent']};border-radius:5px;"
            f"padding:3px 10px;font-size:10px;font-weight:700;"
        )
        self._pyq_badge.setFixedHeight(24)
        q_lay.addWidget(self._pyq_badge)

        # Option buttons — compact height  (font +20%: was 12px → now 15px)
        self.opt_btns = []
        opts_lay = QVBoxLayout(); opts_lay.setSpacing(5)
        for i, label in enumerate(["A", "B", "C", "D"]):
            btn = self._make_opt_btn(f"  {label})")
            btn.setMinimumHeight(40)
            btn.setMaximumHeight(56)
            btn.clicked.connect(lambda _, idx=i: self._answer(idx))
            self.opt_btns.append(btn)
            opts_lay.addWidget(btn)
        q_lay.addLayout(opts_lay)

        # Feedback box — compact
        self.feedback_box = QFrame()
        self.feedback_box.setObjectName("card")
        self.feedback_box.setVisible(False)
        fb_lay = QVBoxLayout(self.feedback_box)
        fb_lay.setContentsMargins(12, 8, 12, 8); fb_lay.setSpacing(4)
        self.fb_result = QLabel("")
        self.fb_result.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        fb_lay.addWidget(self.fb_result)
        self.fb_explain = QLabel("")
        self.fb_explain.setWordWrap(True)
        self.fb_explain.setStyleSheet(
            f"color:{COLORS['text_secondary']};font-size:13px;line-height:1.4;")
        fb_lay.addWidget(self.fb_explain)
        self.fb_source = QLabel("")
        self.fb_source.setStyleSheet(
            f"color:{COLORS['accent']};font-size:10px;font-weight:600;")
        fb_lay.addWidget(self.fb_source)
        q_lay.addWidget(self.feedback_box)

        # Bottom action row: Next button + "Check Needed" verify btn
        bottom_row = QHBoxLayout(); bottom_row.setSpacing(8)

        self.verify_marked_btn = QPushButton("🔍 Verify Flagged Questions")
        self.verify_marked_btn.setObjectName("secondaryBtn")
        self.verify_marked_btn.setMinimumHeight(36)
        self.verify_marked_btn.setVisible(False)
        self.verify_marked_btn.setToolTip(
            "Send all flagged questions to AI for accuracy verification against your database.")
        self.verify_marked_btn.clicked.connect(self._verify_flagged)
        bottom_row.addWidget(self.verify_marked_btn)

        bottom_row.addStretch()

        self.next_btn = QPushButton("Next  →")
        self.next_btn.setObjectName("primaryBtn")
        self.next_btn.setMinimumHeight(36)
        self.next_btn.setMaximumWidth(160)
        self.next_btn.setVisible(False)
        self.next_btn.clicked.connect(self._next_question)
        bottom_row.addWidget(self.next_btn)

        q_lay.addLayout(bottom_row)

        # Give question card a fixed stretch so it always fills available space
        root.addWidget(self.q_card, 1)

        # ── Results card ──────────────────────────────────────────────────
        self.result_card = QFrame(); self.result_card.setObjectName("card")
        self.result_card.setVisible(False)
        r_lay = QVBoxLayout(self.result_card)
        r_lay.setContentsMargins(20, 16, 20, 16); r_lay.setSpacing(8)

        self.r_emoji = QLabel("")
        self.r_emoji.setFont(QFont("Segoe UI", 28))
        self.r_emoji.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.r_score = QLabel("")
        self.r_score.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        self.r_score.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.r_pct = QLabel("")
        self.r_pct.setFont(QFont("Segoe UI", 13))
        self.r_pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.r_quote = QLabel("")
        self.r_quote.setWordWrap(True)
        self.r_quote.setFont(QFont("Segoe UI", 11))
        self.r_quote.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.r_quote.setStyleSheet(
            f"color:{COLORS['text_secondary']};font-style:italic;")

        # Flagged questions summary
        self.r_flagged = QLabel("")
        self.r_flagged.setWordWrap(True)
        self.r_flagged.setStyleSheet(
            f"background:{COLORS['warning_bg']};color:{COLORS['warning']};"
            f"border-left:3px solid {COLORS['warning']};padding:6px 10px;"
            f"border-radius:4px;font-size:11px;")
        self.r_flagged.setVisible(False)

        retry_btn = QPushButton("🔄  Try Again (Same Topic)")
        retry_btn.setObjectName("secondaryBtn")
        retry_btn.setMinimumHeight(34)
        retry_btn.clicked.connect(self._start_quiz)

        verify_btn2 = QPushButton("🔍  Verify Flagged Questions Now")
        verify_btn2.setObjectName("primaryBtn")
        verify_btn2.setMinimumHeight(34)
        verify_btn2.setVisible(False)
        verify_btn2.clicked.connect(self._verify_flagged)
        self._r_verify_btn = verify_btn2

        for w2 in [self.r_emoji, self.r_score, self.r_pct,
                   self.r_quote, self.r_flagged, retry_btn, verify_btn2]:
            r_lay.addWidget(w2)

        root.addWidget(self.result_card, 1)
        root.addStretch()

        # ── QTimer for 50-second countdown ───────────────────────────────
        self._q_timer      = QTimer()
        self._q_timer.setInterval(1000)   # fires every 1 second
        self._q_timer.timeout.connect(self._tick_timer)
        self._time_left    = 50
        self._flagged_idxs = set()        # indices of flagged questions

        return w

    # ── Search Section ────────────────────────────────────────────────────────
    # ── Import from File Section ──────────────────────────────────────────────
    def _build_import_section(self):
        """
        Drag-and-drop panel for importing MCQs from PDF or image files
        directly into question_bank.json.
        Workflow:
          1. Drop / Browse file (PDF, JPG, PNG, TIFF, BMP, GIF)
          2. AI Vision extracts all MCQs with options + answers
          3. Review table shows extracted questions (editable topic)
          4. Click Save → appends to question_bank.json (no overwrites)
        """
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(20, 10, 20, 10)
        root.setSpacing(7)

        # ── Header row ─────────────────────────────────────────────────
        hdr_row = QHBoxLayout()
        hdr_lbl = QLabel("📥  Import Questions from File")
        hdr_lbl.setObjectName("sectionTitle")
        hdr_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        hdr_row.addWidget(hdr_lbl)
        hdr_row.addStretch()

        self._imp_bank_lbl = QLabel("—")
        self._imp_bank_lbl.setStyleSheet(
            f"background:{COLORS['accent_glow']};color:{COLORS['accent']};"
            f"border:1px solid {COLORS['accent']}44;border-radius:10px;"
            f"padding:2px 12px;font-size:11px;font-weight:600;")
        self._refresh_bank_count()
        hdr_row.addWidget(self._imp_bank_lbl)

        # Minimize / Expand button
        self._imp_toggle_btn = QPushButton("▼ Expand")
        self._imp_toggle_btn.setFixedHeight(24)
        self._imp_toggle_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{COLORS['accent']};"
            f"border:1px solid {COLORS['accent']};border-radius:4px;"
            f"font-size:10px;padding:1px 8px;}}"
            f"QPushButton:hover{{background:{COLORS.get('accent_glow','rgba(0,200,160,0.12)')};}}"
        )
        self._imp_toggle_btn.clicked.connect(self._toggle_import_pane)
        hdr_row.addWidget(self._imp_toggle_btn)

        root.addLayout(hdr_row)

        # ── Collapsible body ────────────────────────────────────────────
        self._imp_body = QWidget()
        body_lay = QVBoxLayout(self._imp_body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(7)

        info = QLabel(
            "Drop a PDF exam paper or image scan → AI extracts every MCQ "
            "with options & answers → review & save to bank.  "
            "Supports: PDF · JPG · PNG · TIFF · BMP · GIF"
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            f"background:{COLORS['info_bg']};color:{COLORS['info']};"
            f"border-left:3px solid {COLORS['info']};border-radius:4px;"
            f"padding:5px 10px;font-size:11px;")
        body_lay.addWidget(info)

        # ── File picker row ─────────────────────────────────────────────
        pick_row = QHBoxLayout(); pick_row.setSpacing(8)

        self._imp_file_lbl = QLabel("No file selected")
        self._imp_file_lbl.setStyleSheet(
            f"background:{COLORS['input_bg']};border:1px solid {COLORS['border']};"
            f"border-radius:6px;padding:5px 10px;font-size:11px;"
            f"color:{COLORS['text_secondary']};")
        pick_row.addWidget(self._imp_file_lbl, 4)

        browse_btn = QPushButton("Browse")
        browse_btn.setObjectName("secondaryBtn"); browse_btn.setFixedHeight(32)
        browse_btn.clicked.connect(self._imp_browse)
        pick_row.addWidget(browse_btn)

        # Topic override combo
        topic_lbl = QLabel("Topic:")
        topic_lbl.setStyleSheet(f"color:{COLORS['text_secondary']};font-size:11px;")
        pick_row.addWidget(topic_lbl)

        self._imp_topic_combo = QComboBox()
        self._imp_topic_combo.setFixedHeight(32)
        self._imp_topic_combo.setStyleSheet("font-size:11px;")
        all_topics = ["Auto-detect"] + sorted([
            "IRPWM","IRBM","IRWM","SOD_USFD","TrackMachines",
            "Bridges","Surveying","SOM","RCC_Steel","SoilMechanics",
            "Hydraulics","PHE","ConstructionMat","Establishment",
            "Finance_Stores","Hindi_Rajbhasha","GeneralKnowledge","Miscellaneous",
        ])
        for t in all_topics:
            self._imp_topic_combo.addItem(t)
        pick_row.addWidget(self._imp_topic_combo)

        self._imp_extract_btn = QPushButton("▶  Extract Questions")
        self._imp_extract_btn.setObjectName("primaryBtn")
        self._imp_extract_btn.setFixedHeight(32)
        self._imp_extract_btn.setEnabled(False)
        self._imp_extract_btn.clicked.connect(self._imp_start)
        pick_row.addWidget(self._imp_extract_btn)

        self._imp_stop_btn = QPushButton("⏹ Stop")
        self._imp_stop_btn.setObjectName("secondaryBtn")
        self._imp_stop_btn.setFixedHeight(32)
        self._imp_stop_btn.setVisible(False)
        self._imp_stop_btn.clicked.connect(self._imp_stop)
        pick_row.addWidget(self._imp_stop_btn)
        body_lay.addLayout(pick_row)

        # ── Progress bar ────────────────────────────────────────────────
        prog_row = QHBoxLayout(); prog_row.setSpacing(8)
        self._imp_prog = QProgressBar()
        self._imp_prog.setFixedHeight(5); self._imp_prog.setTextVisible(False)
        self._imp_prog.setRange(0, 100); self._imp_prog.setValue(0)
        prog_row.addWidget(self._imp_prog)
        self._imp_pct = QLabel("")
        self._imp_pct.setFixedWidth(70)
        self._imp_pct.setStyleSheet(f"color:{COLORS['accent']};font-size:11px;font-weight:600;")
        prog_row.addWidget(self._imp_pct)
        body_lay.addLayout(prog_row)

        # ── Log + review area (horizontal split) ────────────────────────
        mid_row = QHBoxLayout(); mid_row.setSpacing(8)

        # Log box
        self._imp_log = QTextEdit()
        self._imp_log.setReadOnly(True)
        self._imp_log.setFixedWidth(300)
        self._imp_log.setMaximumHeight(160)
        self._imp_log.setFont(QFont("Consolas", 9))
        self._imp_log.setStyleSheet(
            f"background:{COLORS['input_bg']};border:1px solid {COLORS['border']};"
            f"border-radius:6px;padding:6px;color:{COLORS['text_secondary']};")
        self._imp_log.setPlaceholderText("Extraction log will appear here…")
        mid_row.addWidget(self._imp_log)

        # Review table
        self._imp_table = QTableWidget(0, 5)
        self._imp_table.setHorizontalHeaderLabels(
            ["#", "Question", "Options (A/B/C/D)", "Correct", "Topic"])
        self._imp_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._imp_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._imp_table.setColumnWidth(0, 30)
        self._imp_table.setColumnWidth(3, 70)
        self._imp_table.setColumnWidth(4, 130)
        self._imp_table.setMaximumHeight(160)
        self._imp_table.setAlternatingRowColors(True)
        self._imp_table.setStyleSheet(
            f"QTableWidget{{font-size:10px;background:{COLORS['input_bg']};"
            f"border:1px solid {COLORS['border']};border-radius:6px;}}")
        self._imp_table.setVisible(False)
        mid_row.addWidget(self._imp_table, 1)
        body_lay.addLayout(mid_row)

        # ── Bottom action row ───────────────────────────────────────────
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        self._imp_count_lbl = QLabel("")
        self._imp_count_lbl.setStyleSheet(f"color:{COLORS['text_muted']};font-size:11px;")
        btn_row.addWidget(self._imp_count_lbl)
        btn_row.addStretch()

        self._imp_clear_btn = QPushButton("🗑 Clear")
        self._imp_clear_btn.setObjectName("secondaryBtn")
        self._imp_clear_btn.setFixedHeight(32)
        self._imp_clear_btn.setEnabled(False)
        self._imp_clear_btn.clicked.connect(self._imp_clear)
        btn_row.addWidget(self._imp_clear_btn)

        self._imp_save_btn = QPushButton("💾  Save to Question Bank")
        self._imp_save_btn.setObjectName("primaryBtn")
        self._imp_save_btn.setFixedHeight(32)
        self._imp_save_btn.setEnabled(False)
        self._imp_save_btn.clicked.connect(self._imp_save)
        btn_row.addWidget(self._imp_save_btn)
        body_lay.addLayout(btn_row)

        # ── Add collapsible body to root ────────────────────────────────
        self._imp_body.setVisible(False)   # start collapsed
        root.addWidget(self._imp_body)

        # Internal state
        self._imp_file_path = None
        self._imp_worker    = None
        self._imp_extracted = []   # list of question dicts ready to save

        # Enable drag-and-drop on the whole widget
        w.setAcceptDrops(True)
        w.dragEnterEvent = self._imp_drag_enter
        w.dropEvent      = self._imp_drop

        return w

    def _imp_drag_enter(self, e):
        if e.mimeData().hasUrls():
            ext = os.path.splitext(
                e.mimeData().urls()[0].toLocalFile())[1].lower()
            if ext in {".pdf",".jpg",".jpeg",".png",".tiff",".tif",".bmp",".gif",".webp"}:
                e.acceptProposedAction()

    def _imp_drop(self, e):
        path = e.mimeData().urls()[0].toLocalFile()
        if path: self._imp_set_file(path)

    def _imp_browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Exam Paper / Image",
            "",
            "Supported Files (*.pdf *.jpg *.jpeg *.png *.tiff *.tif *.bmp *.gif *.webp)"
            ";;PDF Files (*.pdf);;Images (*.jpg *.jpeg *.png *.tiff *.bmp *.gif *.webp)"
        )
        if path: self._imp_set_file(path)

    def _imp_set_file(self, path):
        self._imp_file_path = path
        fname = os.path.basename(path)
        size  = os.path.getsize(path) // 1024
        self._imp_file_lbl.setText(f"📄  {fname}  ({size} KB)")
        self._imp_extract_btn.setEnabled(True)
        self._imp_log.clear()
        self._imp_log.append(f"📄 File: {fname}  ({size} KB)")
        self._imp_log.append("Click ▶ Extract Questions to begin.")

    def _imp_start(self):
        if not self._imp_file_path: return
        key = self._api_key()
        if not key:
            self._imp_log.append("⚠ No API key. Configure in the settings bar above.")
            return
        topic_override = self._imp_topic_combo.currentText()
        if topic_override == "Auto-detect": topic_override = ""

        self._imp_extract_btn.setEnabled(False)
        self._imp_stop_btn.setVisible(True)
        self._imp_save_btn.setEnabled(False)
        self._imp_clear_btn.setEnabled(False)
        self._imp_table.setVisible(False)
        self._imp_prog.setValue(0); self._imp_pct.setText("0%")
        self._imp_extracted = []
        self._imp_log.clear()
        self._imp_count_lbl.setText("")

        self._imp_worker = FileImportWorker(
            self._imp_file_path, key, self._make_ai(), topic_override
        )
        self._imp_worker.log_msg.connect(self._imp_on_log)
        self._imp_worker.progress.connect(self._imp_on_progress)
        self._imp_worker.questions_ready.connect(self._imp_on_done)
        self._imp_worker.start()

    def _imp_stop(self):
        if self._imp_worker: self._imp_worker.stop()
        self._imp_stop_btn.setVisible(False)
        self._imp_extract_btn.setEnabled(True)
        self._imp_log.append("⏹ Stopped.")

    def _imp_on_log(self, msg, level):
        COLORS_LOG = {"info":"#7dd3fc","ok":"#4ade80","warn":"#fbbf24","err":"#f87171"}
        col = COLORS_LOG.get(level, COLORS["text_secondary"])
        self._imp_log.append(f'<span style="color:{col}">{msg}</span>')
        self._imp_log.moveCursor(self._imp_log.textCursor().MoveOperation.End)

    def _imp_on_progress(self, done, total):
        if total:
            pct = int(done / total * 100)
            self._imp_prog.setValue(pct)
            self._imp_pct.setText(f"{done}/{total}")

    def _imp_on_done(self, questions):
        self._imp_stop_btn.setVisible(False)
        self._imp_extract_btn.setEnabled(True)

        if not questions:
            self._imp_log.append("⚠ No MCQs found. Try a different file or check API key.")
            return

        self._imp_extracted = questions
        self._imp_prog.setValue(100)
        self._imp_pct.setText("✓")

        # Populate review table
        self._imp_table.setRowCount(0)
        for i, q in enumerate(questions):
            opts = q.get("options", [])
            opt_str = " / ".join(opts[:4])
            correct_letter = ["A","B","C","D"][min(q.get("correct",0), len(opts)-1)]
            topic = q.get("topic","Miscellaneous")

            self._imp_table.insertRow(i)
            self._imp_table.setItem(i,0, QTableWidgetItem(str(i+1)))
            self._imp_table.setItem(i,1, QTableWidgetItem(q.get("question","")[:120]))
            self._imp_table.setItem(i,2, QTableWidgetItem(opt_str[:100]))
            self._imp_table.setItem(i,3, QTableWidgetItem(correct_letter))

            # Editable topic combo per row
            tc = QComboBox()
            topic_opts = sorted([
                "IRPWM","IRBM","IRWM","SOD_USFD","TrackMachines","Bridges",
                "Surveying","SOM","RCC_Steel","SoilMechanics","Hydraulics",
                "PHE","ConstructionMat","Establishment","Finance_Stores",
                "Hindi_Rajbhasha","GeneralKnowledge","Miscellaneous",
            ])
            for t in topic_opts: tc.addItem(t)
            idx = tc.findText(topic)
            if idx >= 0: tc.setCurrentIndex(idx)
            self._imp_table.setCellWidget(i, 4, tc)

        self._imp_table.setVisible(True)
        self._imp_count_lbl.setText(
            f"✅  {len(questions)} questions extracted — review topics then click Save.")
        self._imp_save_btn.setEnabled(True)
        self._imp_clear_btn.setEnabled(True)
        self._imp_log.append(f"✅ Extracted {len(questions)} questions. Ready to save.")

    def _imp_save(self):
        if not self._imp_extracted: return

        # Read topic overrides from review table
        for i, q in enumerate(self._imp_extracted):
            if i < self._imp_table.rowCount():
                tc = self._imp_table.cellWidget(i, 4)
                if tc: q["topic"] = tc.currentText()

        # Load bank → append → save (NEVER overwrite existing)
        bank = load_qbank()
        added = 0
        for q in self._imp_extracted:
            topic  = q.get("topic","Miscellaneous")
            bucket = bank["topics"].setdefault(topic, [])
            seen   = {x["question"].strip().lower() for x in bucket}
            if q["question"].strip().lower() not in seen:
                q["created"] = datetime.date.today().isoformat()
                q.setdefault("origin","file_import")
                bucket.append(q)
                added += 1

        save_qbank(bank)
        self._refresh_bank_count()

        total = sum(len(v) for k,v in bank["topics"].items() if not k.startswith("_"))
        self._imp_count_lbl.setText(
            f"💾  Saved {added} new questions (bank total: {total}).  "
            f"{len(self._imp_extracted)-added} duplicates skipped.")
        self._imp_log.append(
            f"💾 Saved {added} new | {len(self._imp_extracted)-added} duplicates skipped | "
            f"Bank total: {total}")
        self._imp_save_btn.setEnabled(False)
        self._imp_clear_btn.setEnabled(True)

    def _imp_clear(self):
        self._imp_extracted = []
        self._imp_table.setRowCount(0)
        self._imp_table.setVisible(False)
        self._imp_log.clear()
        self._imp_count_lbl.setText("")
        self._imp_prog.setValue(0); self._imp_pct.setText("")
        self._imp_file_lbl.setText("No file selected")
        self._imp_file_path = None
        self._imp_extract_btn.setEnabled(False)
        self._imp_save_btn.setEnabled(False)
        self._imp_clear_btn.setEnabled(False)

    def _toggle_import_pane(self):
        """Collapse / expand the Import Questions pane body."""
        visible = self._imp_body.isVisible()
        self._imp_body.setVisible(not visible)
        self._imp_toggle_btn.setText("▼ Expand" if visible else "▲ Minimise")

    def _toggle_search_pane(self):
        """Collapse / expand the Code & Manual Search Engine body."""
        visible = self._srch_body.isVisible()
        self._srch_body.setVisible(not visible)
        self._srch_toggle_btn.setText("▼ Expand" if visible else "▲ Minimise")

    def _refresh_bank_count(self):
        try:
            bank  = load_qbank()
            total = sum(len(v) for k,v in bank["topics"].items() if not k.startswith("_"))
            self._imp_bank_lbl.setText(f"Bank: {total} questions")
        except Exception:
            pass

    def _build_search_section(self):
        w = QWidget()
        root = QVBoxLayout(w); root.setContentsMargins(28, 14, 28, 14); root.setSpacing(10)

        # ── Title row with minimize button ────────────────────────────────────
        title_row = QHBoxLayout()
        title = QLabel("🔍  Code & Manual Search Engine")
        title.setObjectName("sectionTitle")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title_row.addWidget(title)
        title_row.addStretch()

        self._srch_toggle_btn = QPushButton("▼ Expand")
        self._srch_toggle_btn.setFixedHeight(24)
        self._srch_toggle_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{COLORS['accent']};"
            f"border:1px solid {COLORS['accent']};border-radius:4px;"
            f"font-size:10px;padding:1px 8px;}}"
            f"QPushButton:hover{{background:{COLORS.get('accent_glow','rgba(0,200,160,0.12)')};}}"
        )
        self._srch_toggle_btn.clicked.connect(self._toggle_search_pane)
        title_row.addWidget(self._srch_toggle_btn)
        root.addLayout(title_row)

        # ── Collapsible body ──────────────────────────────────────────────────
        self._srch_body = QWidget()
        srch_body_lay = QVBoxLayout(self._srch_body)
        srch_body_lay.setContentsMargins(0, 0, 0, 0)
        srch_body_lay.setSpacing(10)

        db_files_txt = ("Searching: main file.pdf · Bridge Related Compilation.pdf"
                        " · Track Related Compilation.pdf · Work Relation Compilation.pdf"
                        "   |   Tip: separate keywords with commas  (e.g.  ballast, gauge, sleeper)")
        db_info = QLabel(db_files_txt)
        db_info.setStyleSheet(f"color:{COLORS['text_muted']};font-size:11px;")
        db_info.setWordWrap(True)
        srch_body_lay.addWidget(db_info)

        # ── Index status bar ──────────────────────────────────────────────────
        idx_row = QHBoxLayout(); idx_row.setSpacing(8)
        self._idx_status = QLabel()
        self._idx_status.setStyleSheet(f"color:{COLORS['text_muted']};font-size:11px;")
        idx_row.addWidget(self._idx_status, 1)
        self._idx_btn = QPushButton("⚙  Build / Rebuild Index")
        self._idx_btn.setObjectName("secondaryBtn")
        self._idx_btn.setFixedHeight(30)
        self._idx_btn.setFixedWidth(185)
        self._idx_btn.clicked.connect(self._build_index)
        idx_row.addWidget(self._idx_btn)
        srch_body_lay.addLayout(idx_row)
        self._refresh_index_status()

        # ── Search bar + AND/OR toggle ────────────────────────────────────────
        s_row = QHBoxLayout(); s_row.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Keywords separated by commas  →  ballast, gauge, 60 kg   "
            "  (AND = all must appear · OR = any match)")
        self.search_input.setMinimumHeight(40)
        self.search_input.returnPressed.connect(self._do_search)
        s_row.addWidget(self.search_input)

        # AND / OR toggle button
        self._mode_btn = QPushButton("OR")
        self._mode_btn.setCheckable(True)
        self._mode_btn.setChecked(False)          # False = OR, True = AND
        self._mode_btn.setFixedHeight(40)
        self._mode_btn.setFixedWidth(56)
        self._mode_btn.setToolTip(
            "OR  — pages containing ANY keyword are shown\n"
            "AND — only pages containing ALL keywords are shown")
        self._mode_btn.setStyleSheet(f"""
            QPushButton {{
                background:{COLORS['info_bg']}; color:{COLORS['info']};
                border:1px solid {COLORS['info']}; border-radius:8px;
                font-size:12px; font-weight:700;
            }}
            QPushButton:checked {{
                background:{COLORS['accent_glow']}; color:{COLORS['accent']};
                border:1px solid {COLORS['accent']};
            }}
        """)
        self._mode_btn.clicked.connect(self._toggle_mode)
        s_row.addWidget(self._mode_btn)

        srch_btn = QPushButton("🔍  Search")
        srch_btn.setObjectName("primaryBtn")
        srch_btn.setMinimumHeight(40); srch_btn.setFixedWidth(110)
        srch_btn.clicked.connect(self._do_search)
        s_row.addWidget(srch_btn)
        srch_body_lay.addLayout(s_row)

        self.search_status = QLabel(
            "Type keywords (comma-separated) and press Search.")
        self.search_status.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:11px;")
        srch_body_lay.addWidget(self.search_status)

        # ── Results + Content side-by-side ────────────────────────────────────
        cols = QHBoxLayout(); cols.setSpacing(12)

        # Left: result list
        left = QVBoxLayout()
        rl = QLabel("MATCHING TOPICS"); rl.setObjectName("fieldLabel")
        left.addWidget(rl)
        self.result_list = QListWidget()
        self.result_list.setMinimumWidth(220)
        self.result_list.setStyleSheet(
            f"QListWidget{{background:{COLORS['input_bg']};border:1px solid {COLORS['border']};"
            f"border-radius:8px;font-size:12px;}}"
            f"QListWidget::item{{padding:8px 10px;border-radius:6px;}}"
            f"QListWidget::item:selected{{background:{COLORS['accent_glow']};"
            f"color:{COLORS['text_primary']};}}"
            f"QListWidget::item:hover{{background:{COLORS['hover_bg']};}}"
        )
        self.result_list.itemClicked.connect(self._fetch_content)
        left.addWidget(self.result_list, 1)
        cols.addLayout(left, 2)

        # Right: content panel + Find bar
        right = QVBoxLayout(); right.setSpacing(4)

        # Header row: label + Find bar
        ch_row = QHBoxLayout(); ch_row.setSpacing(6)
        cl = QLabel("CONTENT FROM MANUAL"); cl.setObjectName("fieldLabel")
        ch_row.addWidget(cl)
        ch_row.addStretch()

        # Find-in-content mini bar
        self._find_input = QLineEdit()
        self._find_input.setPlaceholderText("Find in text…")
        self._find_input.setFixedHeight(28)
        self._find_input.setFixedWidth(170)
        self._find_input.setStyleSheet(
            f"QLineEdit{{background:{COLORS['input_bg']};color:{COLORS['text_primary']};"
            f"border:1px solid {COLORS['border_dark']};"
            f"border-radius:6px;padding:2px 8px;font-size:11px;}}"
            f"QLineEdit:focus{{border-color:{COLORS['accent']};}}"
        )
        self._find_input.returnPressed.connect(self._find_next)
        ch_row.addWidget(self._find_input)

        find_prev_btn = QPushButton("▲")
        find_prev_btn.setFixedSize(28, 28)
        find_prev_btn.setToolTip("Previous match")
        find_prev_btn.setStyleSheet(
            f"QPushButton{{background:{COLORS['input_bg']};border:1px solid {COLORS['border_dark']};"
            f"border-radius:6px;font-size:10px;color:{COLORS['text_secondary']};}}"
            f"QPushButton:hover{{background:{COLORS['hover_bg']};}}"
        )
        find_prev_btn.clicked.connect(self._find_prev)
        ch_row.addWidget(find_prev_btn)

        find_next_btn = QPushButton("▼")
        find_next_btn.setFixedSize(28, 28)
        find_next_btn.setToolTip("Next match (Enter)")
        find_next_btn.setStyleSheet(
            f"QPushButton{{background:{COLORS['input_bg']};border:1px solid {COLORS['border_dark']};"
            f"border-radius:6px;font-size:10px;color:{COLORS['text_secondary']};}}"
            f"QPushButton:hover{{background:{COLORS['hover_bg']};}}"
        )
        find_next_btn.clicked.connect(self._find_next)
        ch_row.addWidget(find_next_btn)

        self._find_count_lbl = QLabel("")
        self._find_count_lbl.setFixedWidth(60)
        self._find_count_lbl.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:10px;")
        ch_row.addWidget(self._find_count_lbl)

        right.addLayout(ch_row)

        self.content_box = QTextEdit()
        self.content_box.setReadOnly(True)
        self.content_box.setPlaceholderText(
            "Select a topic from the list on the left to view content…")
        self.content_box.setStyleSheet(
            f"QTextEdit{{background:{COLORS['input_bg']};border:1px solid {COLORS['border']};"
            f"border-radius:8px;padding:12px;font-size:12px;line-height:1.5;"
            f"color:{COLORS['text_primary']};}}"
            f"QTextEdit:focus{{border-color:{COLORS['accent']};}}"
        )
        right.addWidget(self.content_box, 1)
        cols.addLayout(right, 3)
        srch_body_lay.addLayout(cols, 1)

        root.addWidget(self._srch_body, 1)
        self._srch_body.setVisible(False)   # start collapsed

        # Internal find-state
        self._find_positions = []   # list of QTextCursor positions
        self._find_pos_idx   = -1
        # Auto-rebuild index if stale
        if _index_needs_rebuild():
            self._build_index()

        return w

    # ── AND/OR toggle ─────────────────────────────────────────────────────────
    def _toggle_mode(self):
        if self._mode_btn.isChecked():
            self._mode_btn.setText("AND")
        else:
            self._mode_btn.setText("OR")

    # ── Index management ──────────────────────────────────────────────────────
    def _refresh_index_status(self):
        if os.path.exists(_index_path()):
            import sqlite3
            try:
                conn = sqlite3.connect(_index_path(), check_same_thread=False)
                count = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
                conn.close()
                mtime = datetime.datetime.fromtimestamp(
                    os.path.getmtime(_index_path())).strftime("%d %b %Y  %H:%M")
                self._idx_status.setText(
                    f"⚡ Search index ready — {count} pages indexed  •  Built {mtime}")
                self._idx_status.setStyleSheet(
                    f"color:{COLORS['success']};font-size:11px;font-weight:600;")
            except Exception:
                self._idx_status.setText("⚠️  Index file exists but may be corrupt — rebuild recommended.")
                self._idx_status.setStyleSheet(f"color:{COLORS['warning']};font-size:11px;")
        else:
            self._idx_status.setText(
                "⚠️  No search index found — click 'Build Index' for fast search. "
                "(Without index, each search scans PDFs directly — slower.)")
            self._idx_status.setStyleSheet(f"color:{COLORS['warning']};font-size:11px;")

    def _build_index(self):
        self._idx_btn.setEnabled(False)
        self._idx_btn.setText("⏳  Indexing…")
        self.search_status.setText("🔄  Building search index — please wait…")

        self._index_worker = IndexWorker()
        self._index_worker.progress.connect(
            lambda s: self.search_status.setText(s))
        self._index_worker.finished.connect(self._on_index_done)
        self._index_worker.error.connect(self._on_index_error)
        self._index_worker.start()

    def _on_index_done(self, total):
        self._idx_btn.setEnabled(True)
        self._idx_btn.setText("⚙  Build / Rebuild Index")
        self.search_status.setText(
            f"✅  Index built — {total} pages indexed across all PDFs.  "
            f"Searches are now instant (⚡).")
        self._refresh_index_status()

    def _on_index_error(self, msg):
        self._idx_btn.setEnabled(True)
        self._idx_btn.setText("⚙  Build / Rebuild Index")
        self.search_status.setText(f"❌  Indexing failed: {msg}")

    # ── Quiz Logic ────────────────────────────────────────────────────────────
    def _start_quiz(self):
        idx   = self.topic_combo.currentIndex()
        _, key, _, _ = TOPICS[idx]
        name  = TOPICS[idx][0].split("—")[-1].strip() if "—" in TOPICS[idx][0] else TOPICS[idx][0]
        count = self.q_count_combo.currentData()
        has_api = bool(self._gemini_key() or self._claude_key())

        # ── Surprise Test: pull from all topics ───────────────────────────
        if key == "SurpriseTest":
            cached = get_surprise_test_questions(count)
            if cached:
                self._load_questions(cached)
                self.quiz_status.setText(
                    f"🎲 Surprise Test — {len(cached)} questions from all topics  "
                    f"(PYQ-first, unseen-first ordering)"
                )
            else:
                self.quiz_status.setText(
                    "⚠ No questions in bank yet. Generate questions for individual topics first."
                )
            return

        # ── Step 1: Always load from local bank first ─────────────────────
        cached   = get_cached_questions(key, count)
        prog     = get_topic_progress(key)
        total_qs = prog["total"]

        # Coverage message
        if total_qs > 0:
            seen_pct = int((total_qs - prog["unseen"]) / total_qs * 100)
            if prog["unseen"] > 0:
                coverage_msg = (
                    f"📊 Coverage: {seen_pct}% seen  "
                    f"({prog['unseen']} new questions remaining)"
                )
            else:
                coverage_msg = (
                    f"✅ All {total_qs} questions seen at least once!  "
                    f"Showing repeats (max 2×) until bank grows."
                )
        else:
            coverage_msg = ""

        # ── Step 2a: Bank has enough — start immediately ──────────────────
        if len(cached) >= count:
            self._load_questions(cached[:count])
            bg_msg = "  • 🤖 Refreshing bank in background…" if has_api else ""
            self.quiz_status.setText(
                f"✅ Loaded {count} questions from local bank  "
                f"(bank: {total_qs} total)  • {coverage_msg}{bg_msg}"
            )
            # Silently top-up bank in background if API keys are available
            if has_api:
                self._gen_more_bg(key, name, "", max(5, count))
            return

        # ── Step 2b: Bank has some but not enough — start with what we have
        #            then generate the rest via API ─────────────────────────
        if cached:
            self._load_questions(cached)
            need = count - len(cached)
            if has_api:
                self.quiz_status.setText(
                    f"📚 Started with {len(cached)} bank questions  • {coverage_msg}"
                    f"  • 🤖 Generating {need} more via AI…"
                )
                self._generate_questions(key, name, "", need)
            else:
                self.quiz_status.setText(
                    f"📚 {len(cached)} questions loaded from bank  • {coverage_msg}"
                    f"  • ⚠ Add API key to generate more questions."
                )
            return

        # ── Step 2c: Bank is completely empty — must use API ─────────────
        if has_api:
            self.quiz_status.setText(
                f"🤖 Bank empty for '{name}' — generating {count} questions via AI…"
            )
            self._generate_questions(key, name, "", count)
        else:
            self.quiz_status.setText(
                "⚠ No questions in bank and no API key set.  "
                "Add a Gemini or Claude key in ▼ Configure to generate questions."
            )

    def _generate_questions(self, key, name, api_key, count):
        self.start_btn.setEnabled(False)
        self.q_card.setVisible(False)
        self.result_card.setVisible(False)
        self.prog_bar.setValue(20)

        gk = self._gemini_key()
        ck = self._claude_key()
        if gk and ck:
            self.quiz_status.setText(
                f"🤖 Connecting (Gemini first → Claude fallback) for '{name}'...")
        elif gk:
            self.quiz_status.setText(
                f"🤖 Connecting to Gemini AI to generate questions on '{name}'...")
        else:
            self.quiz_status.setText(
                f"🤖 Connecting to Claude AI to generate questions on '{name}'...")

        self._quiz_worker = QuizWorker(key, name, gemini_key=gk, claude_key=ck, count=count)
        self._quiz_worker.questions_ready.connect(self._on_questions_ready)
        self._quiz_worker.error.connect(self._on_quiz_error)
        self._quiz_worker.status.connect(lambda s: self.quiz_status.setText(s))
        self._quiz_worker.start()

    def _gen_more_bg(self, key, name, api_key, count):
        """Silent background generation to fill cache."""
        gk = self._gemini_key()
        ck = self._claude_key()
        w = QuizWorker(key, name, gemini_key=gk, claude_key=ck, count=count)
        def _bg_save(qs):
            added = append_questions(key, qs)
            if added:
                self.quiz_status.setText(
                    f"✅ {added} new questions added to local cache for '{name}'")
        w.questions_ready.connect(_bg_save)
        w.start()
        self._quiz_worker_bg = w  # keep reference

    def _on_questions_ready(self, questions):
        self.start_btn.setEnabled(True)
        self.prog_bar.setValue(0)
        added = append_questions(questions[0]["topic"], questions)
        self.quiz_status.setText(
            f"✅ {len(questions)} questions generated · {added} new saved to local bank")
        self._load_questions(questions)

    def _on_quiz_error(self, msg):
        self.start_btn.setEnabled(True)
        self.prog_bar.setValue(0)
        self.quiz_status.setText(f"❌ Error: {msg}")

    def _load_questions(self, questions):
        # Sort: PYQ questions first, then AI-generated; shuffle within each group
        pyqs  = [q for q in questions
                 if q.get("origin","").startswith("PYQ") or q.get("pyq_year") or q.get("pyq_date")]
        rest  = [q for q in questions
                 if not (q.get("origin","").startswith("PYQ") or q.get("pyq_year") or q.get("pyq_date"))]
        random.shuffle(pyqs)
        random.shuffle(rest)
        self._questions    = pyqs + rest
        self._q_index      = 0
        self._score        = 0
        self._answered     = False
        self._flagged_idxs = set()      # clear flags for new session
        self._q_timer.stop()            # stop any running timer
        self.result_card.setVisible(False)
        self.verify_marked_btn.setVisible(False)
        self._show_question()

    def _show_question(self):
        if self._q_index >= len(self._questions):
            self._show_results()
            return

        q   = self._questions[self._q_index]
        n   = len(self._questions)
        pct = int((self._q_index / n) * 100)

        self.q_card.setVisible(True)
        self.feedback_box.setVisible(False)
        self.next_btn.setVisible(False)
        self.verify_marked_btn.setVisible(bool(self._flagged_idxs))
        self._answered = False

        self.q_num_label.setText(f"Question {self._q_index + 1} / {n}")
        self.prog_bar.setValue(pct)

        # Difficulty badge
        diff = q.get("difficulty", "medium")
        diff_styles = {
            "easy":   (COLORS["success_bg"],  COLORS["success"]),
            "medium": (COLORS["warning_bg"],  COLORS["warning"]),
            "hard":   (COLORS["error_bg"],    COLORS["error"]),
        }
        bg, fg = diff_styles.get(diff, diff_styles["medium"])
        self.diff_label.setText(diff.upper())
        self.diff_label.setStyleSheet(
            f"background:{bg};color:{fg};font-size:10px;"
            f"border-radius:4px;padding:2px 6px;font-weight:600;")

        self.q_text.setText(q["question"])
        self._apply_q_font()  # apply current user-selected font size

        # ── PYQ badge — show exam year if question is from question bank ──
        origin   = q.get("origin", "")
        pyq_year = q.get("pyq_year") or q.get("pyq_date")
        is_pyq   = origin.startswith("PYQ") or origin == "verified_PYQ" or bool(pyq_year)

        # Try to parse date from origin like "PYQ_2025_06_01"
        if not pyq_year and origin.startswith("PYQ_"):
            parts = origin.split("_")
            if len(parts) >= 2 and parts[1].isdigit() and len(parts[1]) == 4:
                # Full date: PYQ_2025_06_01 → "1 Jun 2025"
                if len(parts) >= 4 and parts[2].isdigit() and parts[3].isdigit():
                    import calendar
                    try:
                        month_abbr = calendar.month_abbr[int(parts[2])]
                        pyq_year   = f"{int(parts[3])} {month_abbr} {parts[1]}"
                    except Exception:
                        pyq_year = parts[1]
                else:
                    pyq_year = parts[1]

        if hasattr(self, "_pyq_badge"):
            if is_pyq:
                badge_text = (f"📅 PYQ — {pyq_year}" if pyq_year
                              else "📅 Previous Year Question")
                self._pyq_badge.setText(badge_text)
                self._pyq_badge.setVisible(True)
            else:
                self._pyq_badge.setVisible(False)

        opts   = q.get("options", [])
        labels = ["A", "B", "C", "D"]
        for i, btn in enumerate(self.opt_btns):
            if i < len(opts):
                btn.setText(f"  {labels[i]})  {opts[i]}")
                btn.setVisible(True)
                btn.setEnabled(True)
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {COLORS['input_bg']};
                        border: 1.5px solid {COLORS['border']};
                        border-radius: 7px; padding: 6px 14px;
                        text-align: left; font-size: 17px;
                        color: {COLORS['text_primary']};
                    }}
                    QPushButton:hover {{
                        background: {COLORS['hover_bg']};
                        border-color: {COLORS['accent']};
                    }}
                    QPushButton:disabled {{ opacity: 0.85; }}
                """)
            else:
                btn.setVisible(False)

        # Update check button appearance
        is_flagged = self._q_index in self._flagged_idxs
        self._update_check_btn(is_flagged)

        self.score_badge.setText(
            f"Score: {self._score}/{self._q_index}  "
            f"({'—' if self._q_index == 0 else f'{int(self._score/self._q_index*100)}%'})")

        # Start 50-second countdown
        self._time_left = 50
        self.timer_label.setText("⏱ 50s")
        self.timer_label.setStyleSheet(
            f"background:{COLORS['warning_bg']};color:{COLORS['warning']};"
            f"border:1px solid {COLORS['warning']};border-radius:6px;"
            f"padding:2px 6px;font-size:11px;font-weight:700;")
        self._q_timer.start()

    def _tick_timer(self):
        """Called every second by QTimer."""
        self._time_left -= 1
        self.timer_label.setText(f"⏱ {self._time_left}s")

        if self._time_left <= 10:
            # Turn red as time runs out
            self.timer_label.setStyleSheet(
                f"background:{COLORS['error_bg']};color:{COLORS['error']};"
                f"border:1px solid {COLORS['error']};border-radius:6px;"
                f"padding:2px 6px;font-size:11px;font-weight:700;")

        if self._time_left <= 0:
            self._q_timer.stop()
            if not self._answered:
                # Time's up — auto-skip (count as unanswered, not wrong)
                self.timer_label.setText("⏰ Time!")
                self._time_up()

    def _time_up(self):
        """Handle time expiry — show correct answer, move on."""
        if self._answered:
            return
        self._answered = True
        q       = self._questions[self._q_index]
        correct = q.get("correct", 0)

        # Highlight correct answer
        for i, btn in enumerate(self.opt_btns):
            btn.setEnabled(False)
            if i == correct:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {COLORS['warning_bg']};
                        border: 2px solid {COLORS['warning']};
                        border-radius: 7px; padding: 6px 14px;
                        text-align: left; font-size: 17px;
                        color: {COLORS['warning']}; font-weight: 600;
                    }}
                """)

        self.feedback_box.setVisible(True)
        self.feedback_box.setStyleSheet(
            f"QFrame#card{{background:{COLORS['warning_bg']};"
            f"border:1px solid {COLORS['warning']};border-radius:8px;}}")
        self.fb_result.setText("⏰  Time's up! Question skipped.")
        self.fb_result.setStyleSheet(
            f"color:{COLORS['warning']};font-size:12px;font-weight:700;")
        opts   = q.get("options", [])
        c_text = opts[correct] if correct < len(opts) else "—"
        self.fb_explain.setText(
            f"Correct answer was: {['A','B','C','D'][correct]}) {c_text}\n"
            + q.get("explanation", ""))
        self.fb_source.setText(
            f"📖 {q.get('source','')}" if q.get("source") else "")

        lbl = "View Results" if self._q_index + 1 >= len(self._questions) else "Next  →"
        self.next_btn.setText(lbl)
        self.next_btn.setVisible(True)

    def _toggle_check_flag(self):
        """Mark / unmark current question for accuracy check."""
        if self._q_index in self._flagged_idxs:
            self._flagged_idxs.discard(self._q_index)
            self._update_check_btn(False)
        else:
            self._flagged_idxs.add(self._q_index)
            self._update_check_btn(True)
        self.verify_marked_btn.setVisible(bool(self._flagged_idxs))
        n = len(self._flagged_idxs)
        self.verify_marked_btn.setText(
            f"🔍 Verify {n} Flagged Question{'s' if n != 1 else ''}")

    def _update_check_btn(self, flagged: bool):
        if flagged:
            self.check_btn.setText("🚩 Flagged ✓")
            self.check_btn.setStyleSheet(
                f"font-size:10px;padding:2px 8px;"
                f"background:{COLORS['error_bg']};color:{COLORS['error']};"
                f"border:1px solid {COLORS['error']};border-radius:5px;")
        else:
            self.check_btn.setText("🚩 Mark for Check")
            self.check_btn.setStyleSheet(
                f"font-size:10px;padding:2px 8px;"
                f"background:{COLORS['warning_bg']};color:{COLORS['warning']};"
                f"border:1px solid {COLORS['warning']};border-radius:5px;")

    def _verify_flagged(self):
        """Send all flagged questions to AI for accuracy verification."""
        if not self._flagged_idxs:
            return
        api_key = self._api_key()
        if not api_key:
            self.quiz_status.setText(
                "⚠  No API key set. Cannot verify questions.")
            return

        flagged_qs = [self._questions[i] for i in sorted(self._flagged_idxs)
                      if i < len(self._questions)]
        if not flagged_qs:
            return

        self.quiz_status.setText(
            f"🔍 Verifying {len(flagged_qs)} flagged questions via AI…")
        self._verify_worker = VerifyWorker(flagged_qs, self._make_ai())
        self._verify_worker.result.connect(self._on_verify_result)
        self._verify_worker.error.connect(
            lambda e: self.quiz_status.setText(f"❌ Verify error: {e}"))
        self._verify_worker.start()

    def _answer(self, chosen_idx):
        if self._answered:
            return
        self._answered = True
        self._q_timer.stop()
        self.timer_label.setText("✓ Done")
        self.timer_label.setStyleSheet(
            f"background:{COLORS['success_bg']};color:{COLORS['success']};"
            f"border:1px solid {COLORS['success']};border-radius:6px;"
            f"padding:2px 6px;font-size:11px;font-weight:700;")

        q       = self._questions[self._q_index]
        correct = q.get("correct", 0)
        is_right= (chosen_idx == correct)
        if is_right:
            self._score += 1

        for i, btn in enumerate(self.opt_btns):
            btn.setEnabled(False)
            if i == correct:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {COLORS['success_bg']};
                        border: 2px solid {COLORS['success']};
                        border-radius: 7px; padding: 6px 14px;
                        text-align: left; font-size: 17px;
                        color: {COLORS['success']}; font-weight: 600;
                    }}
                """)
            elif i == chosen_idx and not is_right:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {COLORS['error_bg']};
                        border: 2px solid {COLORS['error']};
                        border-radius: 7px; padding: 6px 14px;
                        text-align: left; font-size: 17px;
                        color: {COLORS['error']}; font-weight: 600;
                    }}
                """)

        self.feedback_box.setVisible(True)
        if is_right:
            self.fb_result.setText("✅  Correct!")
            self.fb_result.setStyleSheet(
                f"color:{COLORS['success']};font-size:13px;font-weight:700;")
            self.feedback_box.setStyleSheet(
                f"QFrame#card{{background:{COLORS['success_bg']};"
                f"border:1px solid {COLORS['success']};border-radius:8px;}}")
        else:
            opts   = q.get("options", [])
            c_text = opts[correct] if correct < len(opts) else "—"
            self.fb_result.setText(
                f"❌  Incorrect!  Correct: {['A','B','C','D'][correct]}) {c_text}")
            self.fb_result.setStyleSheet(
                f"color:{COLORS['error']};font-size:12px;font-weight:700;")
            self.feedback_box.setStyleSheet(
                f"QFrame#card{{background:{COLORS['error_bg']};"
                f"border:1px solid {COLORS['error']};border-radius:8px;}}")

        self.fb_explain.setText(q.get("explanation", ""))
        src = q.get("source", "")
        self.fb_source.setText(f"📖 {src}" if src else "")

        lbl = "View Results" if self._q_index + 1 >= len(self._questions) else "Next  →"
        self.next_btn.setText(lbl)
        self.next_btn.setVisible(True)

        self.score_badge.setText(
            f"Score: {self._score}/{self._q_index + 1}  "
            f"({int(self._score / (self._q_index + 1) * 100)}%)")

    def _next_question(self):
        self._q_timer.stop()
        self._q_index += 1
        self._show_question()

    def _show_results(self):
        self._q_timer.stop()
        self.q_card.setVisible(False)
        self.result_card.setVisible(True)
        self.prog_bar.setValue(100)

        n   = len(self._questions)
        pct = int(self._score / n * 100) if n else 0

        if pct >= 80:
            emoji = "🏆"; color = COLORS["success"]
            quote = random.choice(ENCOURAGEMENT_QUOTES)
        elif pct >= 60:
            emoji = "👍"; color = COLORS["warning"]
            quote = random.choice(ENCOURAGEMENT_QUOTES[:3])
        else:
            emoji = "📚"; color = COLORS["error"]
            quote = random.choice(MOTIVATION_QUOTES)

        self.r_emoji.setText(emoji)
        self.r_score.setText(f"{self._score} / {n}")
        self.r_score.setStyleSheet(
            f"color:{color};font-size:20px;font-weight:700;")
        self.r_pct.setText(f"{pct}%  correct")
        self.r_pct.setStyleSheet(f"color:{color};font-size:14px;")
        self.r_quote.setText(quote)

        self.score_badge.setText(f"Session: {self._score}/{n} ({pct}%)")

        # Show flagged summary
        nf = len(self._flagged_idxs)
        if nf:
            self.r_flagged.setText(
                f"🚩  {nf} question{'s' if nf > 1 else ''} flagged for accuracy check.\n"
                f"Click 'Verify Flagged Questions Now' to check them via AI.")
            self.r_flagged.setVisible(True)
            self._r_verify_btn.setVisible(True)
            self._r_verify_btn.setText(f"🔍  Verify {nf} Flagged Questions Now")
        else:
            self.r_flagged.setVisible(False)
            self._r_verify_btn.setVisible(False)

    def _on_verify_result(self, report: str):
        """Show verification report in a message-style overlay."""
        self.quiz_status.setText("✅ Verification complete — see report below.")
        # Show as scrollable text in quiz_status area
        from PyQt6.QtWidgets import QDialog, QTextEdit, QPushButton, QVBoxLayout
        dlg = QDialog(self)
        dlg.setWindowTitle("Accuracy Verification Report")
        dlg.resize(680, 480)
        lay = QVBoxLayout(dlg)
        txt = QTextEdit(); txt.setReadOnly(True)
        txt.setFont(QFont("Consolas", 10))
        txt.setPlainText(report)
        lay.addWidget(txt)
        ok = QPushButton("Close"); ok.clicked.connect(dlg.accept)
        lay.addWidget(ok)
        dlg.exec()

    # ── Font-size controls ────────────────────────────────────────────────────
    def _font_size_inc(self):
        self._q_font_size = min(self._q_font_size + 1, 28)
        self.settings.setValue("q_font_size", self._q_font_size)
        self._apply_q_font()

    def _font_size_dec(self):
        self._q_font_size = max(self._q_font_size - 1, 9)
        self.settings.setValue("q_font_size", self._q_font_size)
        self._apply_q_font()

    def _apply_q_font(self):
        """Apply current font size to the question text label."""
        self.q_text.setFont(QFont("Segoe UI", self._q_font_size))

    # ── Theme sync (called by SettingsPanel after theme switch) ──────────────
    def _sync_theme(self):
        """No inline theme controls here — nothing to re-skin."""
        pass





# ── Worker: Extract MCQs from uploaded PDF or image ──────────────────────────
class FileImportWorker(QThread):
    """
    Sends uploaded PDF or image pages to AI Vision in batches.
    Extracts all MCQs with options, correct answer, topic, and source.
    Emits questions_ready with a list of question dicts.
    """
    log_msg         = pyqtSignal(str, str)     # message, level
    progress        = pyqtSignal(int, int)     # done, total
    questions_ready = pyqtSignal(list)

    TOPIC_KEYWORDS = {
        "IRPWM":          ["irpwm","track","rail","sleeper","ballast","gauge","versine",
                           "super elevation","turnout","level crossing","fish plate","p.way",
                           "stop indicator","track renewal","oms","check rail","gfn"],
        "IRBM":           ["irbm","bridge inspection","girder","elastomeric bearing",
                           "curtain wall","camber","tunnel ventilation","vulnerable cutting",
                           "scour","afflux","bridge.*upstream","vertical clearance"],
        "IRWM":           ["irwm","building","roof","section engineer.*work",
                           "building register","plinth","quarter"],
        "SOD_USFD":       ["sod","schedule of dimension","usfd","ultrasonic"],
        "TrackMachines":  ["track machine","xen.*tm","irtmm","stipulated target"],
        "Bridges":        ["bridge.*span","arch","pier.*bridge","well foundation","caisson"],
        "Surveying":      ["survey","levell","benchmark","theodolite","whole to part",
                           "geodetic","circular curve","chord deflection"],
        "SOM":            ["bending moment","shear force","neutral axis","strain",
                           "modulus","elastic","deflect","hooke","moment of inertia"],
        "RCC_Steel":      ["rcc","reinforced concrete","cement","concrete","bleeding",
                           "segregation","formwork","curing","pre-stressed","m20","m25"],
        "SoilMechanics":  ["plate load","bearing capacity","cohesive soil","soil",
                           "void ratio","permeability","consolidation"],
        "Hydraulics":     ["hydraulic depth","open channel","hydrograph","lacey",
                           "silt factor","flood","froude","discharge"],
        "PHE":            ["water supply","chlorine","sewage","bod","sewer","turbidity"],
        "ConstructionMat":["cement","aggregate","timber","brick","mortar","admixture"],
        "Establishment":  ["leave","suspension","charge sheet","railway servant",
                           "compassionate","pension","provident fund","cgegis"],
        "Finance_Stores": ["budget","estimate","plan head","gfr","gem","gst",
                           "deposit work","price variation","dividend","technical sanction"],
        "Hindi_Rajbhasha":["hindi","rajbhasha","official language","raj bhasha"],
        "GeneralKnowledge":["general knowledge","gk","current affairs","president","capital"],
        "Miscellaneous":  [],
    }

    SOURCE_LABELS = {
        "IRPWM":"IRPWM 2020","IRBM":"IRBM — Bridge Manual","IRWM":"IRWM — Works Manual",
        "SOD_USFD":"SOD / USFD","TrackMachines":"IRTMM — Track Machines",
        "Bridges":"IRBM — Bridge Works","Surveying":"Surveying & Levelling",
        "SOM":"Strength of Materials","RCC_Steel":"RCC / Concrete Technology",
        "SoilMechanics":"Soil Mechanics","Hydraulics":"Hydraulics & Hydrology",
        "PHE":"Public Health Engineering","ConstructionMat":"Construction Materials",
        "Establishment":"Establishment Rules","Finance_Stores":"Finance Rules / GFR",
        "Hindi_Rajbhasha":"Hindi / Rajbhasha","GeneralKnowledge":"General Knowledge",
        "Miscellaneous":"Miscellaneous",
    }

    EXTRACT_PROMPT = (
        "Extract EVERY multiple choice question from this exam paper page.\n"
        "Include only questions that have 4 options AND a visible correct answer.\n"
        "Ignore page numbers, question IDs, option IDs, and metadata tags.\n"
        "For deleted/cancelled answers skip that question entirely.\n\n"
        "Return ONLY a JSON array, no markdown:\n"
        '[\n'
        '  {"question":"Full question text","options":["opt A","opt B","opt C","opt D"],'
        '"correct":0,"explanation":"Why correct, citing rule/para","difficulty":"medium",'
        '"source":"e.g. PYQ LDCE June 2023 — IRPWM 2020"}\n'
        "]\n"
        "correct = 0-indexed integer (0=A,1=B,2=C,3=D).\n"
        "If no MCQs found return []."
    )

    def __init__(self, file_path, api_key, ai_provider, topic_override=""):
        super().__init__()
        self.file_path      = file_path
        self.api_key        = api_key
        self.ai             = ai_provider
        self.topic_override = topic_override
        self._stop_flag     = False

    def stop(self): self._stop_flag = True

    def _auto_topic(self, text):
        t = text.lower()
        scores = {}
        for topic, kws in self.TOPIC_KEYWORDS.items():
            score = sum(1 for kw in kws if re.search(kw, t))
            if score: scores[topic] = score
        return max(scores, key=scores.get) if scores else "Miscellaneous"

    def _page_to_b64(self, doc, page_no):
        """Render PDF page to JPEG base64."""
        try:
            import fitz
            pg  = doc[page_no - 1]
            mat = fitz.Matrix(180/72, 180/72)
            pix = pg.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
            return base64.b64encode(pix.tobytes("jpeg", jpg_quality=82)).decode()
        except Exception as e:
            raise RuntimeError(f"Render failed p{page_no}: {e}")

    def _img_to_b64(self, path):
        """Convert image file to JPEG base64, converting unsupported formats."""
        ext = os.path.splitext(path)[1].lower()
        SUPPORTED = {".jpg","jpeg",".png",".gif",".webp"}
        if ext in SUPPORTED:
            with open(path,"rb") as f:
                return base64.b64encode(f.read()).decode(), f"image/{ext.lstrip('.')}"
        # Convert via Pillow
        from PIL import Image as _PIL
        import io as _io
        img = _PIL.open(path)
        if img.mode not in ("RGB","RGBA","L"):
            img = img.convert("RGB")
        buf = _io.BytesIO()
        img.save(buf, format="JPEG", quality=82)
        return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"

    def _extract_page(self, b64, mime):
        """Send one page image to AI and get question list."""
        try:
            raw = self.ai.vision(
                system="You are extracting MCQ questions from exam papers. "
                        "Return only valid JSON arrays.",
                image_b64=b64, mime=mime,
                user=self.EXTRACT_PROMPT,
                max_tokens=4096
            )
            raw = re.sub(r"```json|```","",raw).strip()
            if not raw or raw == "[]": return []
            qs = json.loads(raw)
            return qs if isinstance(qs, list) else []
        except json.JSONDecodeError:
            try:
                m = re.search(r'\[.*\]', raw, re.DOTALL)
                return json.loads(m.group()) if m else []
            except: return []
        except Exception as e:
            self.log_msg.emit(f"  API error: {e}", "warn")
            return []

    def run(self):
        import datetime as dt
        ext      = os.path.splitext(self.file_path)[1].lower()
        all_qs   = []
        today    = dt.date.today().isoformat()

        try:
            if ext == ".pdf":
                # ── PDF: render each page ────────────────────────────
                try:
                    import fitz
                except ImportError:
                    self.log_msg.emit("PyMuPDF not installed. Run: pip install PyMuPDF", "err")
                    self.questions_ready.emit([]); return

                doc    = fitz.open(self.file_path)
                n_pages= len(doc)
                self.log_msg.emit(f"PDF: {n_pages} pages", "info")
                self.progress.emit(0, n_pages)

                for pg_no in range(1, n_pages + 1):
                    if self._stop_flag: break
                    self.log_msg.emit(f"Page {pg_no}/{n_pages}…", "info")
                    try:
                        b64 = self._page_to_b64(doc, pg_no)
                        qs  = self._extract_page(b64, "image/jpeg")
                        if qs:
                            self.log_msg.emit(f"  Page {pg_no}: +{len(qs)} questions", "ok")
                            all_qs.extend(qs)
                    except Exception as e:
                        self.log_msg.emit(f"  Page {pg_no} error: {e}", "warn")
                    self.progress.emit(pg_no, n_pages)
                    time.sleep(0.2)
                doc.close()

            else:
                # ── Single image ─────────────────────────────────────
                self.log_msg.emit(f"Processing image: {os.path.basename(self.file_path)}", "info")
                self.progress.emit(0, 1)
                b64, mime = self._img_to_b64(self.file_path)
                all_qs = self._extract_page(b64, mime)
                self.progress.emit(1, 1)
                if all_qs:
                    self.log_msg.emit(f"+{len(all_qs)} questions extracted", "ok")

        except Exception as e:
            self.log_msg.emit(f"Fatal error: {e}", "err")
            self.questions_ready.emit([]); return

        # ── Post-process: tag topic, source, timestamps ───────────────
        processed = []
        seen_texts = set()
        for q in all_qs:
            qtxt = q.get("question","").strip()
            if not qtxt or len(qtxt) < 10: continue
            if qtxt.lower() in seen_texts: continue
            seen_texts.add(qtxt.lower())

            # Topic
            if self.topic_override:
                q["topic"] = self.topic_override
            elif "topic" not in q or not q["topic"]:
                q["topic"] = self._auto_topic(
                    qtxt + " " + " ".join(q.get("options",[])))

            # Source label
            src_base = self.SOURCE_LABELS.get(q["topic"], q["topic"])
            if "source" not in q or not q["source"]:
                q["source"] = f"File import — {src_base}"

            q["created"] = today
            q.setdefault("difficulty","medium")
            q.setdefault("origin","file_import")
            processed.append(q)

        self.log_msg.emit(
            f"✅ Total: {len(processed)} unique questions extracted", "ok")
        self.questions_ready.emit(processed)


# ── Worker: Accuracy Verifier ─────────────────────────────────────────────────
class VerifyWorker(QThread):
    result = pyqtSignal(str)
    error  = pyqtSignal(str)

    def __init__(self, questions, ai_provider):
        super().__init__()
        self.questions = questions
        self._ai       = ai_provider   # pre-built AIProvider from the panel

    def run(self):
        try:
            ai = self._ai
            lines = ["ACCURACY VERIFICATION REPORT", "=" * 60, ""]
            for i, q in enumerate(self.questions, 1):
                prompt = (
                    f"Verify the accuracy of this MCQ question for LDCE Railway exam:\n\n"
                    f"Q: {q['question']}\n"
                    f"Options: {q['options']}\n"
                    f"Stated correct answer index (0=A): {q['correct']}\n"
                    f"Stated explanation: {q.get('explanation','')}\n"
                    f"Stated source: {q.get('source','')}\n\n"
                    f"Check:\n"
                    f"1. Is the marked answer actually correct?\n"
                    f"2. Is the explanation accurate?\n"
                    f"3. Is the source citation correct?\n"
                    f"4. Any corrections needed?\n\n"
                    f"Reply concisely: VERIFIED / CORRECTION NEEDED, then explain."
                )
                out = ai.chat(
                    system="You are a senior railway engineering examiner verifying MCQ accuracy.",
                    user=prompt, max_tokens=500
                )
                lines.append(f"Q{i}: {q['question'][:80]}...")
                lines.append(f"   Stated answer: {['A','B','C','D'][q['correct']]}")
                lines.append(f"   AI Verdict: {out.strip()}")
                lines.append("")
            self.result.emit("\n".join(lines))
        except Exception as e:
            self.error.emit(str(e))


# ── KnowledgePanel search-logic methods ───────────────────────────────────────
def _kp_do_search(self):
    raw = self.search_input.text().strip()
    if not raw:
        return
    self.result_list.clear()
    self.content_box.clear()
    self._find_positions = []
    self._find_pos_idx   = -1
    self._find_count_lbl.setText("")

    # Prefix the mode so SearchWorker knows AND vs OR
    mode   = "AND" if self._mode_btn.isChecked() else "OR"
    kw_str = f"{mode}:{raw}"

    self.search_status.setText(f"🔍  Searching [{mode}]…")
    self._search_worker = SearchWorker(
        SearchWorker.MODE_SEARCH, keyword=kw_str
    )
    self._search_worker.results_ready.connect(self._on_search_results)
    self._search_worker.status.connect(lambda s: self.search_status.setText(s))
    self._search_worker.error.connect(lambda e: self.search_status.setText(f"❌ {e}"))
    self._search_worker.start()

def _kp_on_search_results(self, results):
    self._search_results = results
    self.result_list.clear()
    if not results:
        self.search_status.setText("❌ No matches found. Try different keywords or switch AND↔OR.")
        return
    self.search_status.setText(
        f"✅ {len(results)} match{'es' if len(results)!=1 else ''} — click a row to view content.")
    for r in results:
        terms   = r.get("terms", [])
        tag     = "  [" + ", ".join(terms) + "]" if terms else ""
        item = QListWidgetItem(
            f"📄 {r['heading']}\n   {r['pdf']}  ·  p.{r['page']+1}{tag}")
        item.setToolTip(r['snippet'])
        self.result_list.addItem(item)

def _kp_fetch_content(self, item):
    idx = self.result_list.currentRow()
    if idx < 0 or idx >= len(self._search_results):
        return
    r = self._search_results[idx]
    self.content_box.setPlainText("Loading content…")
    self.search_status.setText(f"📖 Fetching from {r['pdf']} page {r['page']+1}…")
    self._find_positions = []
    self._find_pos_idx   = -1
    self._find_count_lbl.setText("")

    # Pre-fill the Find bar with the first search term
    terms = r.get("terms", [])
    if terms and not self._find_input.text().strip():
        self._find_input.setText(terms[0])

    kw = self.search_input.text().strip()
    # Strip mode prefix for the fetch worker
    if kw.upper().startswith(("AND:", "OR:")):
        kw = kw.split(":", 1)[1]
    w  = SearchWorker(
        SearchWorker.MODE_FETCH,
        keyword=kw,
        fetch_ref=(r["pdf_path"], r["page"], r["heading"])
    )
    w.content_ready.connect(self._on_content_ready)
    w.error.connect(lambda e: self.content_box.setPlainText(f"Error: {e}"))
    w.status.connect(lambda s: self.search_status.setText(s))
    w.start()
    self._search_worker = w

def _kp_on_content_ready(self, text):
    """Set content then auto-highlight all search terms."""
    self.content_box.setPlainText(text)
    # Run Find immediately if the Find bar already has text
    find_kw = self._find_input.text().strip()
    if find_kw:
        self._run_find(find_kw, go_to_first=True)

# ── Find-in-content logic ──────────────────────────────────────────────────────
def _kp_run_find(self, keyword, go_to_first=False):
    """Highlight all occurrences of keyword in content_box; store cursor list."""
    from PyQt6.QtGui import QTextCharFormat, QColor, QTextCursor
    from PyQt6.QtWidgets import QTextEdit

    self._find_positions = []
    self._find_pos_idx   = -1

    if not keyword:
        # Clear any existing highlights
        cursor = self.content_box.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        fmt = QTextCharFormat()
        cursor.setCharFormat(fmt)
        self._find_count_lbl.setText("")
        return

    kw_lower = keyword.lower()
    doc      = self.content_box.document()
    text     = doc.toPlainText()
    tl       = text.lower()

    # Collect all positions
    start = 0
    while True:
        pos = tl.find(kw_lower, start)
        if pos == -1:
            break
        self._find_positions.append(pos)
        start = pos + 1

    if not self._find_positions:
        self._find_count_lbl.setText("0 found")
        self._find_count_lbl.setStyleSheet(f"color:{COLORS['error']};font-size:10px;")
        return

    # Highlight all matches: yellow background
    hi_fmt = QTextCharFormat()
    hi_fmt.setBackground(QColor("#FFE066"))
    hi_fmt.setForeground(QColor("#1A1E2E"))

    # First clear all existing char formats in document
    clear_cursor = self.content_box.textCursor()
    clear_cursor.select(QTextCursor.SelectionType.Document)
    clear_cursor.setCharFormat(QTextCharFormat())

    kw_len = len(keyword)
    for pos in self._find_positions:
        c = self.content_box.textCursor()
        c.setPosition(pos)
        c.movePosition(QTextCursor.MoveOperation.Right,
                       QTextCursor.MoveMode.KeepAnchor, kw_len)
        c.setCharFormat(hi_fmt)

    total = len(self._find_positions)
    if go_to_first:
        self._find_pos_idx = 0
        self._scroll_to_find(0, total)
    else:
        self._find_count_lbl.setText(f"{total} found")
        self._find_count_lbl.setStyleSheet(
            f"color:{COLORS['success']};font-size:10px;font-weight:600;")

def _kp_scroll_to_find(self, idx, total):
    """Highlight the current match in accent colour and scroll to it."""
    from PyQt6.QtGui import QTextCharFormat, QColor, QTextCursor

    if not self._find_positions:
        return

    # Re-apply yellow to all, then accent to current
    kw     = self._find_input.text().strip()
    kw_len = len(kw)

    hi_fmt  = QTextCharFormat()
    hi_fmt.setBackground(QColor("#FFE066"))
    hi_fmt.setForeground(QColor("#1A1E2E"))

    cur_fmt = QTextCharFormat()
    cur_fmt.setBackground(QColor(COLORS["accent"]))
    cur_fmt.setForeground(QColor(COLORS["navy"]))

    for i, pos in enumerate(self._find_positions):
        c = self.content_box.textCursor()
        c.setPosition(pos)
        c.movePosition(QTextCursor.MoveOperation.Right,
                       QTextCursor.MoveMode.KeepAnchor, kw_len)
        c.setCharFormat(cur_fmt if i == idx else hi_fmt)

    # Scroll to current
    cur_pos = self._find_positions[idx]
    c = self.content_box.textCursor()
    c.setPosition(cur_pos)
    self.content_box.setTextCursor(c)
    self.content_box.ensureCursorVisible()

    self._find_count_lbl.setText(f"{idx+1}/{total}")
    self._find_count_lbl.setStyleSheet(
        f"color:{COLORS['accent']};font-size:10px;font-weight:700;")

def _kp_find_next(self):
    kw = self._find_input.text().strip()
    if not kw:
        return
    # If positions not yet built or keyword changed, rebuild
    if not self._find_positions:
        self._run_find(kw, go_to_first=True)
        return
    total = len(self._find_positions)
    if total == 0:
        return
    self._find_pos_idx = (self._find_pos_idx + 1) % total
    self._scroll_to_find(self._find_pos_idx, total)

def _kp_find_prev(self):
    kw = self._find_input.text().strip()
    if not kw:
        return
    if not self._find_positions:
        self._run_find(kw, go_to_first=True)
        return
    total = len(self._find_positions)
    if total == 0:
        return
    self._find_pos_idx = (self._find_pos_idx - 1) % total
    self._scroll_to_find(self._find_pos_idx, total)

# Patch all methods onto KnowledgePanel
KnowledgePanel._do_search         = _kp_do_search
KnowledgePanel._on_search_results = _kp_on_search_results
KnowledgePanel._fetch_content     = _kp_fetch_content
KnowledgePanel._on_content_ready  = _kp_on_content_ready
KnowledgePanel._run_find          = _kp_run_find
KnowledgePanel._scroll_to_find    = _kp_scroll_to_find
KnowledgePanel._find_next         = _kp_find_next
KnowledgePanel._find_prev         = _kp_find_prev
