"""
CAD Engine v6 — LISP-First Architecture
════════════════════════════════════════════════════════════════════════════════
Pipeline:
  1. Load image / PDF
  2. Claude Vision AI  →  full structured geometry JSON
     (or OpenCV contour tracing if no API key)
  3. Generate AutoLISP script from geometry JSON
  4. Write DXF via ezdxf from same geometry (immediate download, no AutoCAD needed)
  5. Return both .lsp and .dxf for download
════════════════════════════════════════════════════════════════════════════════
AutoLISP output:
  - Draws every detected entity using native AutoCAD commands
  - Creates all layers with correct colours
  - Writes dimension values as TEXT and general notes as MTEXT (annotation-style)
  - User runs (BES-DRAW) in AutoCAD → drawing appears instantly
"""

import os, math, re, tempfile, json, base64, datetime, textwrap
from pathlib import Path

# Drawing output standards (1:1 model mm, text sized from drawing extent)
SCALE_NOTE = "1:1"
TEXT_STYLE_NAME = "STANDARD"
TEXT_MIN_MM = 2.5
TEXT_MAX_DIM_MM = 50.0
TEXT_MAX_TITLE_MM = 35.0
TEXT_FRAC_DIM = 0.025
TEXT_FRAC_ANN = 0.02
TEXT_FRAC_TITLE = 0.015
DEFAULT_FALLBACK_SPAN_MM = 15000.0
ANNOTATION_LINE_TYPES = frozenset({"annotation", "leader"})
TEXT_POLYGON_TYPES = frozenset(
    {"letter", "text", "annotation", "character", "word", "title", "label"}
)


# ─────────────────────────────────────────────────────────────────────────────
VISION_PROMPT = """
You are an expert engineering drawing interpreter (civil / bridge / structural).
Analyse this image thoroughly and extract EVERY piece of geometric and textual information.

Return ONE JSON object — no markdown, no explanation, just the JSON.

{
  "drawing_type": "Half Elevation | Half Section | Plan | Detail | Logo | Other",
  "scale_note":   "1:1",
  "units":        "mm",

  "lines": [
    { "x1":0.0,"y1":0.0,"x2":1.0,"y2":0.0,
      "type":"structural|dimension|centreline|leader|border|annotation",
      "layer":"GEOMETRY|DIMENSIONS|CENTRELINES|BORDER|ANNOTATIONS" }
  ],

  "rectangles": [
    { "x":0.0,"y":0.0,"w":0.1,"h":0.05,
      "filled":false, "label":"", "type":"box|cell|titleblock|slab|footing" }
  ],

  "circles": [
    { "cx":0.5,"cy":0.5,"r":0.02,
      "filled":false, "type":"bolt|hole|symbol|rebar" }
  ],

  "arcs": [
    { "cx":0.5,"cy":0.5,"r":0.05,
      "start_angle":0,"end_angle":180,"type":"haunch|fillet|curve" }
  ],

  "polygons": [
    { "points":[[0.1,0.2],[0.2,0.2],[0.15,0.3]],
      "filled":false, "type":"triangle|shield|letter|section|irregular" }
  ],

  "dimensions": [
    { "value":"3655","unit":"mm",
      "x1":0.2,"y1":0.1,"x2":0.6,"y2":0.1,
      "text_x":0.4,"text_y":0.08,
      "orientation":"horizontal|vertical|diagonal" }
  ],

  "annotations": [
    { "text":"HALF ELEVATION","x":0.3,"y":0.95,
      "size":"large|medium|small",
      "role":"title|label|note|elevation|callout|specification" }
  ],

  "hatching_regions": [
    { "x":0.0,"y":0.0,"w":0.1,"h":0.1,
      "pattern":"ANSI31|ANSI32|ANSI33|ANSI37|AR-CONC|EARTH|NET",
      "scale":1.0, "angle":45,
      "description":"earth fill | concrete | steel | brick" }
  ],

  "symbols": [
    { "x":0.5,"y":0.5,
      "type":"arrow|section_mark|north|weld|rebar|slope",
      "direction":0.0, "description":"" }
  ],

  "levels_elevations": [
    { "label":"BL:168.205","x":0.05,"y":0.72,"value":168.205,"unit":"m" }
  ]
}

COORDINATE RULES:
- x, y are FRACTIONS 0.0–1.0 of image width / height, (0,0) = TOP-LEFT
- scale_note must be "1:1" (model coordinates in mm at full size); units must be "mm"
- Be EXHAUSTIVE for structural geometry — every visible beam, line, and shape
- NEVER trace text, labels, titles, or notes as lines or polygons — put ALL readable text
  only in the "annotations" array (or "dimensions" for dimension values/lines)
- Do not add lines with type "annotation" or layer "ANNOTATIONS"
- For dark filled shapes: set filled=true and trace the full outline as a polygon
- Hatching: bounding box + AutoCAD hatch pattern name only (no individual lines)
"""

# BES drawing-standards knowledge pack (layers, text ladder, chain rules) —
# sourced from .agents/skills/autocad_drawing_standards.md. CAD Process only;
# bore log has its own drawing conventions and does not use this module.
from core.cad_knowledge import build_vision_rules_block
VISION_PROMPT += build_vision_rules_block()


class CADEngine:
    def __init__(self, api_key=""):
        self.api_key     = api_key
        self.image       = None
        self.image_rgb   = None
        self.image_path  = None
        self.file_ext    = ""
        self.img_w       = 0
        self.img_h       = 0
        self.ai_data     = {}

        self.lines        = []
        self.rectangles   = []
        self.circles      = []
        self.arcs         = []
        self.polygons     = []
        self.dimensions   = []
        self.annotations  = []
        self.hatching     = []
        self.symbols      = []
        self.elevations   = []

        self._temp_dir     = tempfile.mkdtemp()
        self._dxf_path     = ""
        self._lsp_path     = ""
        self._mm_per_pixel = 1.0
        self._model_w      = 0.0
        self._model_h      = 0.0
        self._text_heights = {}

    # ── STEP 1: LOAD ─────────────────────────────────────────────────────────
    def load_file(self, path: str):
        self.image_path = path
        self.file_ext   = Path(path).suffix.lower()
        if self.file_ext == ".pdf":
            self._load_pdf(path)
        else:
            self._load_image(path)

    def _load_image(self, path):
        import cv2
        img = cv2.imread(path)
        if img is None:
            raise ValueError(f"Cannot read: {path}")
        h, w = img.shape[:2]
        if max(h, w) > 2500:
            s = 2500 / max(h, w)
            img = cv2.resize(img, (int(w*s), int(h*s)), interpolation=cv2.INTER_AREA)
        self.image_rgb = img
        self.image = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        self.img_h, self.img_w = self.image.shape

    def _load_pdf(self, path):
        try:
            import fitz
            doc = fitz.open(path)
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(3, 3))
            tmp = os.path.join(self._temp_dir, "pdf_page.png")
            pix.save(tmp); doc.close()
            self._load_image(tmp)
        except ImportError:
            raise ImportError("pip install pymupdf")

    # ── STEP 2: DETECT GEOMETRY ──────────────────────────────────────────────
    def detect_geometry(self):
        if self.api_key:
            try:
                self._detect_ai()
            except RuntimeError:
                self._detect_opencv()
            except Exception:
                self._detect_opencv()
        else:
            self._detect_opencv()

    def _detect_ai(self):
        import anthropic

        img_path = self.image_path
        if self.file_ext == ".pdf":
            img_path = os.path.join(self._temp_dir, "pdf_page.png")

        with open(img_path, "rb") as f:
            img_data = base64.standard_b64encode(f.read()).decode()

        ext_map = {
            ".jpg":"image/jpeg",".jpeg":"image/jpeg",".png":"image/png",
            ".tiff":"image/jpeg",".tif":"image/jpeg",".bmp":"image/png"
        }
        mt = ext_map.get(Path(img_path).suffix.lower(), "image/png")

        client = anthropic.Anthropic(api_key=self.api_key)

        # ── Attempt 1: full structured JSON ──────────────────────────────
        parsed = None
        last_error = ""
        try:
            resp = client.messages.create(
                model="claude-sonnet-4-6", max_tokens=8096,
                messages=[{"role":"user","content":[
                    {"type":"image","source":{"type":"base64","media_type":mt,"data":img_data}},
                    {"type":"text","text":VISION_PROMPT}
                ]}]
            )
            raw = resp.content[0].text.strip()
            parsed = self._safe_parse_json(raw)
        except Exception as e:
            last_error = str(e)

        # ── Attempt 2: simpler prompt if JSON failed ──────────────────────
        if parsed is None:
            try:
                simple_prompt = (
                    "Analyse this engineering drawing. "
                    "Return ONLY valid JSON — no markdown, no comments, no trailing commas. "
                    "All string values must escape any quotes or backslashes. "
                    "Use this minimal schema:\n"
                    '{"drawing_type":"","scale_note":"1:1","units":"mm",'
                    '"lines":[],"rectangles":[],"circles":[],"arcs":[],'
                    '"polygons":[],"dimensions":[],"annotations":[],'
                    '"hatching_regions":[],"symbols":[],"levels_elevations":[]}'
                    "\n\nFill in the arrays with detected entities. "
                    "Coordinates as fractions 0.0-1.0 of image size, (0,0)=top-left. "
                    "Do not represent text as lines or polygons; use annotations[] for all text."
                )
                resp2 = client.messages.create(
                    model="claude-sonnet-4-6", max_tokens=8096,
                    messages=[{"role":"user","content":[
                        {"type":"image","source":{"type":"base64","media_type":mt,"data":img_data}},
                        {"type":"text","text":simple_prompt}
                    ]}]
                )
                raw2 = resp2.content[0].text.strip()
                parsed = self._safe_parse_json(raw2)
            except Exception as e:
                last_error = str(e)

        # ── Attempt 3: annotations-only (just get the text out) ───────────
        if parsed is None:
            try:
                text_prompt = (
                    "List every text label, dimension value, and annotation visible in this drawing. "
                    "Return ONLY a JSON array of objects: "
                    '[{"text":"value","x":0.5,"y":0.5}] '
                    "where x,y are fractions 0.0-1.0 of image size. "
                    "Escape all quotes inside string values with \\\"."
                )
                resp3 = client.messages.create(
                    model="claude-sonnet-4-6", max_tokens=4096,
                    messages=[{"role":"user","content":[
                        {"type":"image","source":{"type":"base64","media_type":mt,"data":img_data}},
                        {"type":"text","text":text_prompt}
                    ]}]
                )
                raw3 = resp3.content[0].text.strip()
                ann_list = self._safe_parse_json(raw3)
                if isinstance(ann_list, list):
                    parsed = {
                        "drawing_type":"Engineering Drawing","scale_note":"1:1","units":"mm",
                        "lines":[],"rectangles":[],"circles":[],"arcs":[],"polygons":[],
                        "dimensions":[],"annotations":ann_list,
                        "hatching_regions":[],"symbols":[],"levels_elevations":[]
                    }
            except Exception as e:
                last_error = str(e)

        # ── If all AI attempts failed → OpenCV fallback ───────────────────
        if parsed is None:
            raise RuntimeError(
                f"AI analysis failed after 3 attempts. Last error: {last_error}. "
                "Falling back to OpenCV mode."
            )

        self.ai_data = parsed
        self._populate_from_ai()

    def _safe_parse_json(self, raw: str) -> dict:
        """
        Robust JSON parser:
          1. Strip markdown fences
          2. Extract first { ... } block
          3. Fix common issues: trailing commas, unescaped quotes in values
          4. Parse
        Returns parsed dict/list or raises ValueError.
        """
        import re

        # Strip markdown
        text = raw.replace("```json","").replace("```","").strip()

        # Extract the first complete JSON object or array
        # Find opening brace/bracket
        start = -1
        open_char = close_char = None
        for i, ch in enumerate(text):
            if ch == '{':
                start = i; open_char = '{'; close_char = '}'; break
            elif ch == '[':
                start = i; open_char = '['; close_char = ']'; break

        if start == -1:
            raise ValueError("No JSON object found in response")

        # Walk to find matching close
        depth = 0
        in_string = False
        escape_next = False
        end = -1
        for i in range(start, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == '\\' and in_string:
                escape_next = True
                continue
            if ch == '"' and not escape_next:
                in_string = not in_string
                continue
            if not in_string:
                if ch == open_char:
                    depth += 1
                elif ch == close_char:
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break

        if end == -1:
            # Truncated — try to salvage by closing open structures
            text = text[start:]
            # Remove trailing comma before attempting fix
            text = re.sub(r',\s*$', '', text.rstrip())
            # Count unclosed braces/brackets
            opens   = text.count('{') - text.count('}')
            aopens  = text.count('[') - text.count(']')
            text   += ']' * max(0, aopens) + '}' * max(0, opens)
        else:
            text = text[start:end]

        # Fix trailing commas before } or ]
        text = re.sub(r',(\s*[}\]])', r'\1', text)

        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Last resort: use json5-style tolerant parse via ast eval trick
        # Replace Python-style booleans just in case
        text = text.replace(': True', ': true').replace(': False', ': false').replace(': None', ': null')
        return json.loads(text)

    def _populate_from_ai(self):
        W, H = float(self.img_w), float(self.img_h)
        d = self.ai_data
        def px(v): return float(v or 0) * W
        def py(v): return float(v or 0) * H

        for ln in d.get("lines", []):
            ltype = str(ln.get("type", "structural")).lower()
            layer = str(ln.get("layer", "GEOMETRY")).upper()
            if ltype in ANNOTATION_LINE_TYPES or layer == "ANNOTATIONS":
                continue
            self.lines.append((px(ln.get("x1")), py(ln.get("y1")),
                                px(ln.get("x2")), py(ln.get("y2")),
                                layer, ltype))
        for r in d.get("rectangles", []):
            self.rectangles.append((px(r.get("x")), py(r.get("y")),
                                     px(r.get("w")), py(r.get("h")),
                                     r.get("label",""), r.get("type","box"),
                                     bool(r.get("filled",False))))
        for c in d.get("circles", []):
            self.circles.append((px(c.get("cx")), py(c.get("cy")),
                                  px(c.get("r")), c.get("type","hole"),
                                  bool(c.get("filled",False))))
        for a in d.get("arcs", []):
            self.arcs.append((px(a.get("cx")), py(a.get("cy")), px(a.get("r")),
                               float(a.get("start_angle",0)), float(a.get("end_angle",180)),
                               a.get("type","curve")))
        for p in d.get("polygons", []):
            ptype = str(p.get("type", "irregular")).lower()
            pts = [(px(pt[0]), py(pt[1])) for pt in (p.get("points") or [])]
            if len(pts) < 3:
                continue
            if ptype in TEXT_POLYGON_TYPES:
                cx = sum(pt[0] for pt in pts) / len(pts)
                cy = sum(pt[1] for pt in pts) / len(pts)
                self.annotations.append({
                    "text": p.get("label", "").strip() or ptype.upper(),
                    "x": cx, "y": cy, "size": "medium", "role": "label",
                })
                continue
            self.polygons.append((pts, ptype, bool(p.get("filled", False))))
        for dm in d.get("dimensions", []):
            self.dimensions.append({
                "value":  str(dm.get("value","")).strip(),
                "unit":   dm.get("unit","mm"),
                "x1": px(dm.get("x1")), "y1": py(dm.get("y1")),
                "x2": px(dm.get("x2")), "y2": py(dm.get("y2")),
                "text_x": px(dm.get("text_x")), "text_y": py(dm.get("text_y")),
                "orientation": dm.get("orientation","horizontal"),
            })
        for an in d.get("annotations", []):
            self.annotations.append({
                "text": str(an.get("text","")).strip(),
                "x": px(an.get("x")), "y": py(an.get("y")),
                "size": an.get("size","medium"), "role": an.get("role","label")
            })
        for ht in d.get("hatching_regions", []):
            self.hatching.append({
                "x": px(ht.get("x")), "y": py(ht.get("y")),
                "w": px(ht.get("w")), "h": py(ht.get("h")),
                "pattern": ht.get("pattern","ANSI31"),
                "scale":   float(ht.get("scale",1.0)),
                "angle":   float(ht.get("angle",45)),
                "description": ht.get("description","fill"),
            })
        for sy in d.get("symbols", []):
            self.symbols.append({
                "x": px(sy.get("x")), "y": py(sy.get("y")),
                "type": sy.get("type","symbol"),
                "direction": float(sy.get("direction",0)),
                "description": sy.get("description",""),
            })
        for el in d.get("levels_elevations", []):
            self.elevations.append({
                "label": str(el.get("label","")).strip(),
                "x": px(el.get("x")), "y": py(el.get("y")),
                "value": el.get("value"), "unit": el.get("unit","m"),
            })

    def _detect_opencv(self):
        import cv2, numpy as np
        gray = self.image.copy()
        H, W = gray.shape
        blur = cv2.GaussianBlur(gray, (5,5), 0)
        _, t1 = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        _, t2 = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY     + cv2.THRESH_OTSU)
        t_ad  = cv2.adaptiveThreshold(blur,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY_INV,15,8)
        def score(m):
            c,_ = cv2.findContours(m,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            return sum(1 for x in c if cv2.contourArea(x)>200)
        binary = max([t1,t2,t_ad], key=score)
        k = np.ones((3,3),np.uint8)
        binary = cv2.morphologyEx(binary,cv2.MORPH_CLOSE,k,iterations=2)
        contours,_ = cv2.findContours(binary,cv2.RETR_TREE,cv2.CHAIN_APPROX_SIMPLE)
        MIN_AREA = max(100, W*H*0.0002)
        seen = set()
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < MIN_AREA or area > W*H*0.97: continue
            peri = cv2.arcLength(cnt,True)
            if peri < 10: continue
            approx = cv2.approxPolyDP(cnt, 0.008*peri, True)
            pts = [(float(p[0][0]),float(p[0][1])) for p in approx]
            n = len(pts)
            if n < 3: continue
            bx,by,bw,bh = cv2.boundingRect(cnt)
            key = (round(bx/6)*6,round(by/6)*6,round(bw/6)*6,round(bh/6)*6)
            if key in seen: continue
            seen.add(key)
            circ = (4*math.pi*area)/(peri*peri) if peri>0 else 0
            if circ>0.80 and n>8:
                (cx,cy),r = cv2.minEnclosingCircle(cnt)
                if r>3: self.circles.append((float(cx),float(cy),float(r),"detected",False))
            elif n==4:
                rect = cv2.minAreaRect(cnt)
                ra = rect[1][0]*rect[1][1]
                if ra>0 and abs(area-ra)/ra<0.15:
                    self.rectangles.append((float(bx),float(by),float(bw),float(bh),"","box",False))
                else:
                    self.polygons.append((pts,"quadrilateral",False))
            elif n > 6 and area < W * H * 0.002:
                continue
            else:
                self.polygons.append((pts,"polygon",False))
        # structural lines
        for min_len,ksize,horiz in [
            (max(40,int(W*0.05)),(max(40,int(W*0.05)),1),True),
            (max(40,int(H*0.05)),(1,max(40,int(H*0.05))),False)
        ]:
            kk = cv2.getStructuringElement(cv2.MORPH_RECT,ksize)
            mask = cv2.morphologyEx(binary,cv2.MORPH_OPEN,kk)
            lcs,_ = cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            for lc in lcs:
                lx,ly,lw,lh = cv2.boundingRect(lc)
                if horiz and lw>min_len:
                    self.lines.append((float(lx),float(ly+lh//2),float(lx+lw),float(ly+lh//2),"GEOMETRY","structural"))
                elif not horiz and lh>min_len:
                    self.lines.append((float(lx+lw//2),float(ly),float(lx+lw//2),float(ly+lh),"GEOMETRY","structural"))
        self._extract_tesseract()

    def _extract_tesseract(self):
        try:
            import pytesseract
            from PIL import Image as PILImage
            data = pytesseract.image_to_data(PILImage.fromarray(self.image),
                       output_type=pytesseract.Output.DICT, config="--psm 11 --oem 3")
            for i,text in enumerate(data["text"]):
                text=text.strip()
                conf=int(data.get("conf",[-1])[i])
                if len(text)<2 or conf<40: continue
                x=float(data["left"][i])+float(data["width"][i])/2
                y=float(data["top"][i]) +float(data["height"][i])/2
                self.annotations.append({"text":text,"x":x,"y":y,"size":"medium","role":"label"})
        except Exception: pass

    # ── STEP 3 ────────────────────────────────────────────────────────────────
    def extract_dimensions(self):
        if not self.api_key and not self.annotations:
            self._extract_tesseract()

    # ── STEP 4 ────────────────────────────────────────────────────────────────
    def build_layers(self):
        MIN_LEN = 8
        clean, seen = [], set()
        for ln in self.lines:
            x1,y1,x2,y2=ln[0],ln[1],ln[2],ln[3]
            layer=ln[4] if len(ln)>4 else "GEOMETRY"
            ltype=ln[5] if len(ln)>5 else "structural"
            if math.hypot(x2-x1,y2-y1)<MIN_LEN: continue
            if (x1,y1)>(x2,y2): x1,y1,x2,y2=x2,y2,x1,y1
            key=(round(x1/3)*3,round(y1/3)*3,round(x2/3)*3,round(y2/3)*3)
            if key not in seen:
                seen.add(key); clean.append((x1,y1,x2,y2,layer,ltype))
        self.lines=clean
        clean_p,seen_p=[],set()
        for item in self.polygons:
            pts,ptype=item[0],item[1]
            filled=item[2] if len(item)>2 else False
            if len(pts)<3: continue
            cx=round(sum(p[0] for p in pts)/len(pts)/5)*5
            cy=round(sum(p[1] for p in pts)/len(pts)/5)*5
            key=(cx,cy,len(pts))
            if key not in seen_p:
                seen_p.add(key); clean_p.append((pts,ptype,filled))
        self.polygons=clean_p
        self._strip_annotation_geometry()
        self._filter_spurious_dimensions()
        self._calibrate_model_scale()
        self._derive_text_heights()
        self._layout_text_positions()

    def _strip_annotation_geometry(self):
        """Remove lines/polygons that duplicate annotation text as geometry."""
        clean_lines = []
        for ln in self.lines:
            ltype = (ln[5] if len(ln) > 5 else "structural").lower()
            layer = (ln[4] if len(ln) > 4 else "GEOMETRY").upper()
            if ltype in ANNOTATION_LINE_TYPES or layer == "ANNOTATIONS":
                continue
            clean_lines.append(ln)
        self.lines = clean_lines

        clean_polys = []
        for item in self.polygons:
            pts, ptype = item[0], str(item[1]).lower()
            if ptype in TEXT_POLYGON_TYPES:
                cx = sum(p[0] for p in pts) / len(pts)
                cy = sum(p[1] for p in pts) / len(pts)
                self.annotations.append({
                    "text": ptype.upper(), "x": cx, "y": cy,
                    "size": "medium", "role": "label",
                })
                continue
            clean_polys.append(item)
        self.polygons = clean_polys

    @staticmethod
    def _parse_dim_value(val) -> float:
        s = str(val or "").strip().replace(",", "")
        m = re.search(r"[\d.]+", s)
        return float(m.group()) if m else 0.0

    def _structural_span_px(self) -> float:
        """Longest structural witness in pixels (lines or dimension witnesses)."""
        best = 0.0
        for ln in self.lines:
            ltype = (ln[5] if len(ln) > 5 else "structural").lower()
            if ltype in ("dimension", "leader", "annotation", "border"):
                continue
            best = max(best, math.hypot(ln[2] - ln[0], ln[3] - ln[1]))
        for dm in self.dimensions:
            best = max(
                best,
                math.hypot(dm["x2"] - dm["x1"], dm["y2"] - dm["y1"]),
            )
        return best

    def _infer_span_mm(self) -> float:
        """Best-effort real-world span (mm) from dimensions or annotations."""
        vals = []
        for dm in self.dimensions:
            val = self._parse_dim_value(dm.get("value"))
            unit = str(dm.get("unit", "mm")).lower()
            if val <= 0:
                continue
            if unit in ("m", "metre", "meters", "meter"):
                val *= 1000.0
            vals.append(val)
        if vals:
            return max(vals)
        for an in self.annotations:
            m = re.search(r"(\d{3,6})\s*mm", str(an.get("text", "")), re.I)
            if m:
                vals.append(float(m.group(1)))
        if vals:
            return max(vals)
        return DEFAULT_FALLBACK_SPAN_MM

    def _infer_fallback_mm_per_pixel(self) -> float:
        span_px = max(
            self._structural_span_px(),
            max(float(self.img_w), float(self.img_h), 1.0) * 0.35,
        )
        span_mm = self._infer_span_mm()
        return max(0.1, span_mm / span_px)

    @staticmethod
    def _median_ratio(ratios: list) -> float:
        ratios = sorted(ratios)
        return ratios[len(ratios) // 2]

    def _filter_spurious_dimensions(self):
        """Drop title-block / noise dimensions that cause bad calibration or label spam."""
        if not self.dimensions:
            return
        img_h = max(float(self.img_h), 1.0)
        img_w = max(float(self.img_w), 1.0)
        tb_y = img_h * 0.82
        min_witness = max(12.0, min(img_w, img_h) * 0.02)
        clean = []
        for dm in self.dimensions:
            val = self._parse_dim_value(dm.get("value"))
            d_px = math.hypot(dm["x2"] - dm["x1"], dm["y2"] - dm["y1"])
            cy = (dm["y1"] + dm["y2"]) / 2.0
            if val <= 0:
                continue
            if cy >= tb_y and val < 500:
                continue
            if d_px < min_witness and val <= 100:
                continue
            clean.append(dm)
        self.dimensions = clean

    def _calibrate_model_scale(self):
        """Convert pixel coordinates to model mm at 1:1 using dimension witnesses."""
        span_px = max(float(self.img_w), float(self.img_h), 1.0)
        min_witness = max(12.0, span_px * 0.015)
        ratios = []
        for dm in self.dimensions:
            val = self._parse_dim_value(dm.get("value"))
            unit = str(dm.get("unit", "mm")).lower()
            if unit in ("m", "metre", "meters", "meter"):
                val *= 1000.0
            d_px = math.hypot(dm["x2"] - dm["x1"], dm["y2"] - dm["y1"])
            if val > 50 and d_px >= min_witness:
                ratios.append(val / d_px)
        if ratios:
            med = self._median_ratio(ratios)
            filtered = [r for r in ratios if med / 4 <= r <= med * 4]
            self._mm_per_pixel = self._median_ratio(filtered or ratios)
        else:
            self._mm_per_pixel = self._infer_fallback_mm_per_pixel()

        if abs(self._mm_per_pixel - 1.0) > 1e-6:
            self._scale_all_geometry(self._mm_per_pixel)
        self._model_w = float(self.img_w) * self._mm_per_pixel
        self._model_h = float(self.img_h) * self._mm_per_pixel

        if self.ai_data:
            self.ai_data["scale_note"] = SCALE_NOTE
            self.ai_data["units"] = "mm"

    def _model_extent(self) -> float:
        return max(self._model_w, self._model_h, float(self.img_w), float(self.img_h), 1.0)

    def _derive_text_heights(self):
        ext = self._model_extent()
        dim_h = max(TEXT_MIN_MM, min(TEXT_MAX_DIM_MM, ext * TEXT_FRAC_DIM))
        ann_h = max(TEXT_MIN_MM, min(TEXT_MAX_DIM_MM, ext * TEXT_FRAC_ANN))
        title_h = max(TEXT_MIN_MM, min(TEXT_MAX_TITLE_MM, ext * TEXT_FRAC_TITLE))
        self._text_heights = {
            "dim": dim_h,
            "ann": ann_h,
            "title": title_h,
            "extent": ext,
        }

    def _text_height_for_annotation(self, an: dict) -> float:
        if not self._text_heights:
            self._derive_text_heights()
        th = self._text_heights
        role = str(an.get("role", "label")).lower()
        size = str(an.get("size", "medium")).lower()
        if role == "title" or size == "large":
            return th["title"]
        if role in ("note", "specification"):
            return th["ann"] * 0.9
        return th["ann"]

    def _scale_all_geometry(self, factor: float):
        def sc(v):
            return float(v) * factor

        scaled = []
        for ln in self.lines:
            scaled.append((sc(ln[0]), sc(ln[1]), sc(ln[2]), sc(ln[3]), *ln[4:]))
        self.lines = scaled

        self.rectangles = [
            (sc(r[0]), sc(r[1]), sc(r[2]), sc(r[3]), *r[4:]) for r in self.rectangles
        ]
        self.circles = [(sc(c[0]), sc(c[1]), sc(c[2]), *c[3:]) for c in self.circles]
        self.arcs = [(sc(a[0]), sc(a[1]), sc(a[2]), a[3], a[4], *a[5:]) for a in self.arcs]
        self.polygons = [
            ([(sc(p[0]), sc(p[1])) for p in pts], ptype, filled)
            for pts, ptype, filled in (
                (item[0], item[1], item[2] if len(item) > 2 else False) for item in self.polygons
            )
        ]
        for dm in self.dimensions:
            for k in ("x1", "y1", "x2", "y2", "text_x", "text_y"):
                if k in dm:
                    dm[k] = sc(dm[k])
        for an in self.annotations:
            an["x"] = sc(an["x"])
            an["y"] = sc(an["y"])
        for ht in self.hatching:
            for k in ("x", "y", "w", "h"):
                ht[k] = sc(ht[k])
        for sy in self.symbols:
            sy["x"] = sc(sy["x"])
            sy["y"] = sc(sy["y"])
        for el in self.elevations:
            el["x"] = sc(el["x"])
            el["y"] = sc(el["y"])

    @staticmethod
    def _text_bbox(text: str, x: float, y: float, height: float):
        w = max(height, len(text) * height * 0.55)
        h = height * 1.25
        return (x - w * 0.5, y - h * 0.5, x + w * 0.5, y + h * 0.5)

    @staticmethod
    def _boxes_overlap(a, b, gap: float) -> bool:
        return not (
            a[2] + gap < b[0] or b[2] + gap < a[0] or
            a[3] + gap < b[1] or b[3] + gap < a[1]
        )

    def _layout_text_positions(self):
        """Nudge annotation and dimension label positions to reduce overlap at 1:1."""
        if not self._text_heights:
            self._derive_text_heights()
        dim_h = self._text_heights["dim"]
        gap = dim_h * 0.35
        placed = []

        for an in self.annotations:
            x, y = float(an["x"]), float(an["y"])
            text = an.get("text", "").strip()
            if not text:
                continue
            h = self._text_height_for_annotation(an)
            for _ in range(48):
                bbox = self._text_bbox(text, x, y, h)
                if not any(self._boxes_overlap(bbox, pb, gap) for pb in placed):
                    break
                y += h * 1.35
            an["x"], an["y"] = x, y
            an["_layout_h"] = h
            placed.append(self._text_bbox(text, x, y, h))

        for dm in self.dimensions:
            val = str(dm.get("value", "")).strip()
            if not val:
                continue
            unit = dm.get("unit", "mm")
            lbl = val if unit in val else f"{val} {unit}"
            x = float(dm.get("text_x") or (dm["x1"] + dm["x2"]) / 2)
            y = float(dm.get("text_y") or (dm["y1"] + dm["y2"]) / 2)
            for _ in range(48):
                bbox = self._text_bbox(lbl, x, y, dim_h)
                if not any(self._boxes_overlap(bbox, pb, gap) for pb in placed):
                    break
                y += dim_h * 1.35
            dm["text_x"], dm["text_y"] = x, y
            placed.append(self._text_bbox(lbl, x, y, dim_h))

    def _canvas_size(self):
        return (
            self._model_w if self._model_w > 0 else float(self.img_w) * self._mm_per_pixel,
            self._model_h if self._model_h > 0 else float(self.img_h) * self._mm_per_pixel,
        )

    # ── STEP 5a: GENERATE AutoLISP ───────────────────────────────────────────
    def generate_lisp(self) -> str:
        """
        Generates a complete AutoLISP script.
        Run (BES-DRAW) inside AutoCAD to recreate the entire drawing.
        """
        W, H = self._canvas_size()
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        src= os.path.basename(self.image_path or "unknown")
        dtype = self.ai_data.get("drawing_type","Engineering Drawing") if self.ai_data else "OpenCV Detection"
        scale = self.ai_data.get("scale_note", SCALE_NOTE) if self.ai_data else SCALE_NOTE
        if not self._text_heights:
            self._derive_text_heights()
        dim_h = self._text_heights["dim"]
        ann_h = self._text_heights["ann"]
        title_h = self._text_heights["title"]
        mode  = "Claude Vision AI" if self.api_key else "OpenCV Contour"

        def fy(y): return H - float(y)   # flip Y for AutoCAD
        def fp(v): return f"{float(v):.4f}"  # format point value

        lines_out = []

        def w(s=""):
            lines_out.append(s)

        def lisp_pt(x, y):
            return f"(list {fp(x)} {fp(y)})"

        # ── Header ────────────────────────────────────────────────────────
        w(f"; ═══════════════════════════════════════════════════════════════")
        w(f"; Bridge Engineering Suite v2.0 — AutoLISP Drawing Script")
        w(f"; Source   : {src}")
        w(f"; Type     : {dtype}")
        w(f"; Scale    : {scale}")
        w(f"; Mode     : {mode}")
        w(f"; Generated: {ts}")
        w(f"; Canvas   : {int(W)} x {int(H)} mm  ({scale})")
        w(f"; ───────────────────────────────────────────────────────────────")
        w(f"; USAGE: Load this file in AutoCAD, then type: (BES-DRAW)")
        w(f"; ═══════════════════════════════════════════════════════════════")
        w()

        # ── Layer setup function ──────────────────────────────────────────
        w("(defun BES-MAKE-LAYERS ()")
        layer_defs = [
            ("GEOMETRY",    7,   "Continuous",  "Structural lines and shapes"),
            ("DIMENSIONS",  3,   "Continuous",  "Dimension lines and values"),
            ("CENTRELINES", 1,   "CENTER",       "Centre lines"),
            ("ANNOTATIONS", 2,   "Continuous",  "Labels, notes, titles"),
            ("HATCHING",    8,   "Continuous",  "Hatch region outlines"),
            ("ELEVATIONS",  3,   "Continuous",  "RL/FL/BL level markers"),
            ("SYMBOLS",     6,   "Continuous",  "Symbols and markers"),
            ("BORDER",      5,   "Continuous",  "Drawing border"),
            ("TITLEBLOCK",  4,   "Continuous",  "Title block information"),
        ]
        for lname, lcolor, ltype, _ in layer_defs:
            w(f'  (command "._LAYER" "M" "{lname}" "C" "{lcolor}" "{lname}" "L" "{ltype}" "{lname}" "")')
        w(")")
        w()

        # ── Helper: set layer ─────────────────────────────────────────────
        w("(defun BES-SET-LAYER (lname)")
        w('  (command "._CLAYER" lname)')
        w(")")
        w()

        # ── Helper: draw line ─────────────────────────────────────────────
        w("(defun BES-LINE (x1 y1 x2 y2)")
        w('  (command "._LINE" (list x1 y1) (list x2 y2) "")')
        w(")")
        w()

        # ── Helper: draw polyline ─────────────────────────────────────────
        w("(defun BES-PLINE (pts closed)")
        w('  (command "._PLINE")')
        w("  (foreach pt pts")
        w('    (command pt)')
        w("  )")
        w('  (if closed (command "C") (command ""))')
        w(")")
        w()

        # ── Helper: draw circle ───────────────────────────────────────────
        w("(defun BES-CIRCLE (cx cy r)")
        w('  (command "._CIRCLE" (list cx cy) r)')
        w(")")
        w()

        # ── Helper: draw arc ──────────────────────────────────────────────
        w("(defun BES-ARC (cx cy r sa ea)")
        w('  (command "._ARC" "C" (list cx cy) (polar (list cx cy) (/ (* sa pi) 180) r)')
        w('           "A" (- ea sa))')
        w(")")
        w()

        # ── Helper: MTEXT ─────────────────────────────────────────────────
        w("(defun BES-TEXT (txt x y h)")
        w('  (command "._MTEXT" (list x y) "H" h "W" 0 txt "")')
        w(")")
        w()

        # ── Helper: hatch ─────────────────────────────────────────────────
        w("(defun BES-HATCH (pattern scale angle x1 y1 x2 y2)")
        w('  (command "._RECTANG" (list x1 y1) (list x2 y2))')
        w('  (command "._HATCH" "P" pattern scale angle "L" "")')
        w(")")
        w()

        # ─────────────────────────────────────────────────────────────────
        # MAIN DRAW FUNCTION
        # ─────────────────────────────────────────────────────────────────
        w("(defun c:BES-DRAW ( / old-layer)")
        w('  (setq old-layer (getvar "CLAYER"))')
        w('  (command "._UNDO" "BE")')
        w()
        w("  ; ── Create layers ──────────────────────────────────────────")
        w("  (BES-MAKE-LAYERS)")
        w()

        # ── Border ───────────────────────────────────────────────────────
        m = dim_h * 0.1
        w("  ; ── Border ────────────────────────────────────────────────")
        w('  (BES-SET-LAYER "BORDER")')
        w(f'  (BES-PLINE (list {lisp_pt(-m,-m)} {lisp_pt(W+m,-m)} {lisp_pt(W+m,H+m)} {lisp_pt(-m,H+m)}) T)')
        w()

        # ── Lines ────────────────────────────────────────────────────────
        if self.lines:
            w("  ; ── Structural / annotation lines ───────────────────────")
            layer_cache = None
            for ln in self.lines:
                x1,y1,x2,y2=ln[0],ln[1],ln[2],ln[3]
                layer=ln[4] if len(ln)>4 else "GEOMETRY"
                ltype=ln[5] if len(ln)>5 else "structural"
                if ltype in ANNOTATION_LINE_TYPES or layer == "ANNOTATIONS":
                    continue
                if ltype=="centreline": layer="CENTRELINES"
                elif ltype=="dimension": layer="DIMENSIONS"
                elif ltype=="border":   layer="BORDER"
                if layer != layer_cache:
                    w(f'  (BES-SET-LAYER "{layer}")')
                    layer_cache = layer
                w(f"  (BES-LINE {fp(x1)} {fp(fy(y1))} {fp(x2)} {fp(fy(y2))})")
            w()

        # ── Rectangles ───────────────────────────────────────────────────
        if self.rectangles:
            w("  ; ── Rectangles ───────────────────────────────────────────")
            w('  (BES-SET-LAYER "GEOMETRY")')
            for item in self.rectangles:
                rx,ry,rw,rh=item[0],item[1],item[2],item[3]
                label=item[4] if len(item)>4 else ""
                rtype=item[5] if len(item)>5 else "box"
                layer= "TITLEBLOCK" if rtype=="titleblock" else "GEOMETRY"
                w(f'  (BES-SET-LAYER "{layer}")')
                pts_str = " ".join([
                    lisp_pt(rx,     fy(ry)),
                    lisp_pt(rx+rw,  fy(ry)),
                    lisp_pt(rx+rw,  fy(ry+rh)),
                    lisp_pt(rx,     fy(ry+rh)),
                ])
                w(f"  (BES-PLINE (list {pts_str}) T)")
                if label:
                    w(f'  (BES-SET-LAYER "ANNOTATIONS")')
                    safe = label.replace('"','\\"')
                    w(f'  (BES-TEXT "{safe}" {fp(rx+rw*0.5)} {fp(fy(ry+rh*0.5))} {fp(ann_h)})')
            w()

        # ── Circles ──────────────────────────────────────────────────────
        if self.circles:
            w("  ; ── Circles ──────────────────────────────────────────────")
            w('  (BES-SET-LAYER "GEOMETRY")')
            for item in self.circles:
                cx,cy,r=item[0],item[1],item[2]
                if r < 2: continue
                w(f"  (BES-CIRCLE {fp(cx)} {fp(fy(cy))} {fp(r)})")
            w()

        # ── Arcs ─────────────────────────────────────────────────────────
        if self.arcs:
            w("  ; ── Arcs ─────────────────────────────────────────────────")
            w('  (BES-SET-LAYER "GEOMETRY")')
            for item in self.arcs:
                cx,cy,r,sa,ea=item[0],item[1],item[2],item[3],item[4]
                if r < 2: continue
                dsa = (360-ea) % 360
                dea = (360-sa) % 360
                w(f"  (BES-ARC {fp(cx)} {fp(fy(cy))} {fp(r)} {fp(dsa)} {fp(dea)})")
            w()

        # ── Polygons ─────────────────────────────────────────────────────
        if self.polygons:
            w("  ; ── Polygons / complex shapes ───────────────────────────")
            w('  (BES-SET-LAYER "GEOMETRY")')
            for item in self.polygons:
                pts,ptype=item[0],item[1]
                filled=item[2] if len(item)>2 else False
                if len(pts)<3: continue
                pts_str = " ".join(lisp_pt(p[0],fy(p[1])) for p in pts)
                w(f"  ; {ptype}")
                w(f"  (BES-PLINE (list {pts_str}) T)")
            w()

        # ── Dimensions ───────────────────────────────────────────────────
        if self.dimensions:
            w("  ; ── Dimensions ───────────────────────────────────────────")
            w('  (BES-SET-LAYER "DIMENSIONS")')
            for dm in self.dimensions:
                val=dm.get("value",""); unit=dm.get("unit","mm")
                x1,y1=dm.get("x1",0),dm.get("y1",0)
                x2,y2=dm.get("x2",0),dm.get("y2",0)
                tx,ty=dm.get("text_x",0),dm.get("text_y",0)
                orient=dm.get("orientation","horizontal")
                if x1 or y1 or x2 or y2:
                    w(f"  (BES-LINE {fp(x1)} {fp(fy(y1))} {fp(x2)} {fp(fy(y2))})")
                    tick = max(dim_h * 0.15, H * 0.002)
                    if orient=="horizontal":
                        for ex,ey in [(x1,y1),(x2,y2)]:
                            w(f"  (BES-LINE {fp(ex)} {fp(fy(ey)-tick)} {fp(ex)} {fp(fy(ey)+tick)})")
                    else:
                        for ex,ey in [(x1,y1),(x2,y2)]:
                            w(f"  (BES-LINE {fp(ex-tick)} {fp(fy(ey))} {fp(ex+tick)} {fp(fy(ey))})")
                if val:
                    lbl = val if unit in val else f"{val} {unit}"
                    safe = lbl.replace('"','\\"')
                    mx = tx if tx else (x1+x2)/2
                    my = ty if ty else (y1+y2)/2
                    w(f'  (BES-TEXT "{safe}" {fp(mx)} {fp(fy(my))} {fp(dim_h)})')
            w()

        # ── Annotations (MTEXT only — no line geometry) ───────────────────
        if self.annotations:
            w("  ; ── Annotations / text ──────────────────────────────────")
            role_color = {"title":"ANNOTATIONS","label":"ANNOTATIONS",
                          "note":"ANNOTATIONS","callout":"ANNOTATIONS",
                          "elevation":"ELEVATIONS","specification":"ANNOTATIONS"}
            cur_layer  = None
            for an in self.annotations:
                text=an.get("text","").strip()
                if not text: continue
                role=an.get("role","label")
                layer=role_color.get(role,"ANNOTATIONS")
                if layer != cur_layer:
                    w(f'  (BES-SET-LAYER "{layer}")')
                    cur_layer=layer
                safe=text.replace('"','\\"').replace("\n"," ")
                ah = an.get("_layout_h") or self._text_height_for_annotation(an)
                w(f'  (BES-TEXT "{safe}" {fp(an["x"])} {fp(fy(an["y"]))} {fp(ah)})')
            w()

        # ── Hatching regions ─────────────────────────────────────────────
        if self.hatching:
            w("  ; ── Hatching regions ────────────────────────────────────")
            w('  (BES-SET-LAYER "HATCHING")')
            for ht in self.hatching:
                hx,hy,hw,hh=ht["x"],ht["y"],ht["w"],ht["h"]
                pat=ht.get("pattern","ANSI31")
                hscale=ht.get("scale",1.0)
                hangle=ht.get("angle",45)
                desc=ht.get("description","fill")
                w(f'  ; Hatch: {desc}')
                w(f'  (BES-HATCH "{pat}" {fp(hscale)} {fp(hangle)} {fp(hx)} {fp(fy(hy+hh))} {fp(hx+hw)} {fp(fy(hy))})')
            w()

        # ── Symbols ──────────────────────────────────────────────────────
        if self.symbols:
            w("  ; ── Symbols ─────────────────────────────────────────────")
            w('  (BES-SET-LAYER "SYMBOLS")')
            sym_s = dim_h * 0.2
            for sy in self.symbols:
                sx,sy_y=sy["x"],sy["y"]
                stype=sy.get("type","symbol")
                sdesc=sy.get("description","")
                w(f"  ; Symbol: {stype} — {sdesc}")
                w(f"  (BES-LINE {fp(sx-sym_s)} {fp(fy(sy_y))} {fp(sx+sym_s)} {fp(fy(sy_y))})")
                w(f"  (BES-LINE {fp(sx)} {fp(fy(sy_y)-sym_s)} {fp(sx)} {fp(fy(sy_y)+sym_s)})")
            w()

        # ── Elevation markers ─────────────────────────────────────────────
        if self.elevations:
            w("  ; ── Elevation / level markers ───────────────────────────")
            w('  (BES-SET-LAYER "ELEVATIONS")')
            tick = dim_h * 0.25
            for el in self.elevations:
                label=el.get("label",""); ex,ey=el.get("x",0),el.get("y",0)
                w(f"  (BES-LINE {fp(ex-tick)} {fp(fy(ey))} {fp(ex+tick*3)} {fp(fy(ey))})")
                safe=label.replace('"','\\"')
                w(f'  (BES-TEXT "{safe}" {fp(ex+tick*3.5)} {fp(fy(ey))} {fp(ann_h)})')
            w()

        # ── Title block (margin below geometry, smaller text) ─────────────
        w("  ; ── Title block ─────────────────────────────────────────────")
        w('  (BES-SET-LAYER "TITLEBLOCK")')
        tb_x = W * 0.02
        tb_entries = [
            (f"DRAWING TYPE: {dtype}", title_h),
            (f"SOURCE: {src}", title_h),
            (f"SCALE: {scale}", title_h),
            ("UNITS: mm", title_h),
            (f"MODE: {mode}", title_h),
            (f"GENERATED: {ts}", title_h),
            (f"ENTITIES: {len(self.lines)}L {len(self.rectangles)}R "
             f"{len(self.circles)}C {len(self.polygons)}P "
             f"{len(self.annotations)}T", title_h),
            ("BRIDGE ENGINEERING SUITE v2.0", title_h * 1.1),
        ]
        cur_y = -(title_h * 2.0)
        for txt, tb_h_val in tb_entries:
            safe = txt.replace('"','\\"')
            w(f'  (BES-TEXT "{safe}" {fp(tb_x)} {fp(cur_y)} {fp(tb_h_val)})')
            cur_y -= tb_h_val * 2.0
        w()

        # ── Zoom extents + close ──────────────────────────────────────────
        w('  (command "._ZOOM" "E")')
        w('  (command "._UNDO" "END")')
        w(f'  (setvar "CLAYER" old-layer)')
        w('  (princ (strcat "\\nBES-DRAW complete. Entities drawn on " (itoa (length (ssget "_A"))) " objects total."))')
        w("  (princ)")
        w(")")
        w()
        w('; ── Auto-run on load ──────────────────────────────────────────')
        w('; Remove the line below if you want to call (BES-DRAW) manually')
        w('(BES-DRAW)')

        lisp_code = "\n".join(lines_out)
        stem = Path(self.image_path).stem if self.image_path else "output"
        self._lsp_path = os.path.join(self._temp_dir, f"{stem}_BES.lsp")
        with open(self._lsp_path, "w", encoding="utf-8") as f:
            f.write(lisp_code)
        return self._lsp_path

    # ── STEP 5b: WRITE DXF (immediate use, no AutoCAD needed) ────────────────
    def write_dxf(self) -> str:
        try:
            import ezdxf
        except ImportError:
            raise ImportError("pip install ezdxf")

        doc = ezdxf.new(dxfversion="R2010")
        doc.header["$INSUNITS"]    = 4
        doc.header["$MEASUREMENT"] = 1
        doc.header["$LTSCALE"]     = 1.0
        doc.header["$DIMSCALE"]    = 1.0
        msp = doc.modelspace()

        for name,color in [
            ("GEOMETRY",7),("DIMENSIONS",3),("CENTRELINES",1),
            ("ANNOTATIONS",2),("HATCHING",8),("TITLEBLOCK",4),
            ("BORDER",5),("SYMBOLS",6),("ELEVATIONS",3),
        ]:
            doc.layers.add(name=name,color=color)

        if not self._text_heights:
            self._derive_text_heights()
        dim_h = self._text_heights["dim"]
        ann_h = self._text_heights["ann"]
        title_h = self._text_heights["title"]

        if TEXT_STYLE_NAME not in doc.styles:
            doc.styles.add(TEXT_STYLE_NAME, font="txt.shx", height=0)

        W, H = self._canvas_size()

        def fy(y): return H - float(y)

        def add_text(txt, x, y, layer, height, color=None):
            att = {"layer": layer, "height": height, "style": TEXT_STYLE_NAME}
            if color is not None:
                att["color"] = color
            try:
                msp.add_text(txt, dxfattribs=att).set_placement((float(x), fy(y)))
            except Exception:
                pass

        def add_mtext(txt, x, y, layer, height, color=None):
            att = {"layer": layer, "char_height": height, "style": TEXT_STYLE_NAME}
            if color is not None:
                att["color"] = color
            try:
                msp.add_mtext(txt, dxfattribs=att).set_location((float(x), fy(y)))
            except Exception:
                add_text(txt, x, y, layer, height, color)

        lc_map={"GEOMETRY":7,"DIMENSIONS":3,"CENTRELINES":1,"BORDER":5}

        # Lines
        for ln in self.lines:
            x1,y1,x2,y2=ln[0],ln[1],ln[2],ln[3]
            layer=ln[4] if len(ln)>4 else "GEOMETRY"
            ltype=ln[5] if len(ln)>5 else "structural"
            if ltype in ANNOTATION_LINE_TYPES or layer == "ANNOTATIONS":
                continue
            if ltype=="centreline": layer="CENTRELINES"
            elif ltype=="dimension": layer="DIMENSIONS"
            elif ltype=="border":   layer="BORDER"
            msp.add_line((x1,fy(y1)),(x2,fy(y2)),dxfattribs={"layer":layer,"color":lc_map.get(layer,7)})

        # Rectangles
        for item in self.rectangles:
            rx,ry,rw,rh=item[0],item[1],item[2],item[3]
            label=item[4] if len(item)>4 else ""; rtype=item[5] if len(item)>5 else "box"
            layer="TITLEBLOCK" if rtype=="titleblock" else "GEOMETRY"
            msp.add_lwpolyline([(rx,fy(ry)),(rx+rw,fy(ry)),(rx+rw,fy(ry+rh)),(rx,fy(ry+rh))],
                               close=True,dxfattribs={"layer":layer,"color":7})
            if label: add_mtext(label, rx + rw * 0.5, ry + rh * 0.5, "ANNOTATIONS", ann_h)

        # Circles
        for item in self.circles:
            cx,cy,r=item[0],item[1],item[2]
            if r>2: msp.add_circle((cx,fy(cy)),r,dxfattribs={"layer":"GEOMETRY","color":7})

        # Arcs
        for item in self.arcs:
            cx,cy,r,sa,ea=item[0],item[1],item[2],item[3],item[4]
            if r<2: continue
            try: msp.add_arc((cx,fy(cy)),r,(360-ea)%360,(360-sa)%360,dxfattribs={"layer":"GEOMETRY","color":7})
            except: pass

        # Polygons
        for item in self.polygons:
            pts=item[0]
            cad_pts=[(p[0],fy(p[1])) for p in pts]
            if len(cad_pts)>=3:
                msp.add_lwpolyline(cad_pts,close=True,dxfattribs={"layer":"GEOMETRY","color":7})

        # Dimensions
        for dm in self.dimensions:
            val=dm.get("value",""); unit=dm.get("unit","mm")
            x1,y1,x2,y2=dm.get("x1",0),dm.get("y1",0),dm.get("x2",0),dm.get("y2",0)
            tx,ty=dm.get("text_x",0),dm.get("text_y",0)
            orient=dm.get("orientation","horizontal")
            if x1 or y1 or x2 or y2:
                msp.add_line((x1,fy(y1)),(x2,fy(y2)),dxfattribs={"layer":"DIMENSIONS","color":3})
                tick=max(dim_h*0.15, H*0.002)
                if orient=="horizontal":
                    for ex,ey in [(x1,y1),(x2,y2)]:
                        msp.add_line((ex,fy(ey)-tick),(ex,fy(ey)+tick),dxfattribs={"layer":"DIMENSIONS","color":3})
                else:
                    for ex,ey in [(x1,y1),(x2,y2)]:
                        msp.add_line((ex-tick,fy(ey)),(ex+tick,fy(ey)),dxfattribs={"layer":"DIMENSIONS","color":3})
            if val:
                lbl=val if unit in val else f"{val} {unit}"
                add_text(lbl, tx or (x1 + x2) / 2, ty or (y1 + y2) / 2, "DIMENSIONS", dim_h, color=3)

        # Annotations — MTEXT on ANNOTATIONS layer (not line geometry)
        role_color = {"title": 2, "label": 2, "note": 2, "callout": 2, "elevation": 3}
        for an in self.annotations:
            text = an.get("text", "").strip()
            if not text:
                continue
            role = an.get("role", "label")
            layer = "ELEVATIONS" if role == "elevation" else "ANNOTATIONS"
            ah = an.get("_layout_h") or self._text_height_for_annotation(an)
            add_mtext(text, an["x"], an["y"], layer, ah, color=role_color.get(role, 2))

        # Hatching outlines
        for ht in self.hatching:
            hx,hy,hw,hh=ht["x"],ht["y"],ht["w"],ht["h"]
            msp.add_lwpolyline([(hx,fy(hy)),(hx+hw,fy(hy)),(hx+hw,fy(hy+hh)),(hx,fy(hy+hh))],
                               close=True,dxfattribs={"layer":"HATCHING","color":8})
            add_mtext(
                f"[{ht.get('pattern', 'ANSI31')}: {ht.get('description', 'fill')}]",
                hx + hw * 0.1, hy + hh * 0.5, "HATCHING", ann_h * 0.85, color=8,
            )

        # Elevations
        for el in self.elevations:
            label=el.get("label",""); ex,ey=el.get("x",0),el.get("y",0)
            tick=dim_h*0.25
            msp.add_line((ex-tick,fy(ey)),(ex+tick*3,fy(ey)),dxfattribs={"layer":"ELEVATIONS","color":3})
            add_mtext(label, ex + tick * 3.5, ey, "ELEVATIONS", ann_h, color=3)

        # Border
        m=dim_h*0.1
        msp.add_lwpolyline([(-m,-m),(W+m,-m),(W+m,H+m),(-m,H+m)],close=True,
                           dxfattribs={"layer":"BORDER","color":5,"lineweight":50})

        # Title block
        ts=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        src=os.path.basename(self.image_path or "unknown")
        dtype=self.ai_data.get("drawing_type","Engineering Drawing") if self.ai_data else "OpenCV Detection"
        scale=self.ai_data.get("scale_note", SCALE_NOTE) if self.ai_data else SCALE_NOTE
        mode="Claude Vision AI" if self.api_key else "Smart OpenCV"
        tb_x = W * 0.02
        entries=[
            (f"DRAWING TYPE: {dtype}", 4, title_h),
            (f"SOURCE: {src}", 4, title_h),
            (f"SCALE: {scale}", 4, title_h),
            ("UNITS: mm", 4, title_h),
            (f"MODE: {mode}", 4, title_h),
            (f"GENERATED: {ts}", 4, title_h),
            ("BRIDGE ENGINEERING SUITE v2.0", 5, title_h * 1.1),
        ]
        cur_y=-(title_h * 2.0)
        for txt, col, th in entries:
            try:
                msp.add_text(
                    txt,
                    dxfattribs={
                        "layer": "TITLEBLOCK",
                        "height": th,
                        "color": col,
                        "style": TEXT_STYLE_NAME,
                    },
                ).set_placement((tb_x, cur_y))
            except Exception:
                pass
            cur_y -= th * 2.0

        doc.header["$EXTMIN"]=(0.0, cur_y - title_h * 2, 0.0)
        doc.header["$EXTMAX"]=(W,H,0.0)
        doc.header["$LIMMIN"]=(0.0,0.0)
        doc.header["$LIMMAX"]=(W,H)

        stem=Path(self.image_path).stem if self.image_path else "output"
        self._dxf_path=os.path.join(self._temp_dir,f"{stem}_BES.dxf")
        doc.saveas(self._dxf_path)
        return self._dxf_path
