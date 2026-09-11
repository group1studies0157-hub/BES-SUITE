"""Read-only scan of VS Code storage DBs for GLM/Z.AI/provider/model config clues."""
import glob
import os
import re
import sqlite3

APPDATA = os.environ["APPDATA"]
ROOTS = [
    os.path.join(APPDATA, "Code", "User", "globalStorage"),
    os.path.join(APPDATA, "Code", "User", "workspaceStorage"),
]

KEY_RE = re.compile(r"(apiprovider|apimodelid|glm|z[\.\-]?ai\b|openrouter|kilocode|cline\.bot)", re.I)
SNIP_RE = re.compile(r".{0,70}(glm[-0-9a-z._]*|\"?api(ModelId|Provider)\"?\s*:\s*\"[^\"]{0,40}\").{0,40}", re.I)


def deep_walk(obj):
    """Yield key=value for interesting leaf fields inside parsed JSON."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                kl = str(k).lower()
                if isinstance(v, (dict, list)):
                    stack.append(v)
                elif isinstance(v, str) and any(t in kl for t in ("apiprovider", "apimodelid")):
                    yield f"{k}={v}"
                elif isinstance(v, str) and KEY_RE.search(kl):
                    yield f"{k}={v[:60]}"


def scan_db(db_path):
    try:
        uri = "file:{}?mode=ro&immutable=1".format(db_path.replace("\\", "/"))
        con = sqlite3.connect(uri, uri=True)
        cur = con.cursor()
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    except Exception as exc:
        print(f"[ERR] {db_path}: {exc}")
        return
    findings = {}
    raw_snippets = []
    for tname in tables:
        try:
            rows = cur.execute(f'SELECT * FROM "{tname}"').fetchall()
        except Exception:
            continue
        for row in rows:
            for cell in row:
                if isinstance(cell, bytes):
                    try:
                        text = cell.decode("utf-8", "ignore")
                    except Exception:
                        continue
                elif isinstance(cell, str):
                    text = cell
                else:
                    continue
                low = text.lower()
                for tok in ("glm-5.3-flash", "glm-5.3", "apiModelId", "apiProvider", "z.ai"):
                    c = low.count(tok.lower())
                    if c and tok not in findings:
                        findings[tok] = c
                    elif c:
                        findings[tok] += c
                # apiProvider / apiModelId pairs wherever they sit
                for mval in re.findall(r'"(apiProvider|apiModelId)"\s*:\s*"([^"]{1,60})"', text)[:6]:
                    raw_snippets.append(f"{mval[0]}={mval[1]}")
                # raw 'glm' mentions context (first few)
                if len(raw_snippets) < 12:
                    for mval in SNIP_RE.finditer(text):
                        frag = mval.group(0)
                        if "glm" in frag.lower():
                            raw_snippets.append("ctx:" + frag.replace("\n", " ")[:140])
                            break
    if findings or raw_snippets:
        short = db_path.split("Code\\User")[-1]
        print(f"\n=== {short} ===")
        print("counts:", {k: v for k, v in sorted(findings.items())})
        for s in dict.fromkeys(raw_snippets):
            print("   ", s)


print("scanning...")
for root in ROOTS:
    for db_path in glob.glob(os.path.join(root, "**", "state.vscdb"), recursive=True):
        scan_db(db_path)
print("\nDONE")
