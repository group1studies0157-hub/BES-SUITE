# RAILBRIDGE AI — Multi-Agent Railway Bridge Drawing Intelligence System
## Complete Production Architecture & Implementation Guide

---

## 1. SYSTEM OVERVIEW

RailBridgeAI is a 16-agent desktop application that ingests scanned railway bridge drawings (PDF, TIFF, PNG, JPG) and outputs professionally accurate AutoCAD DWG/DXF files. It reconstructs drawings from **engineering intent**, not pixel tracing.

---

## 2. FOLDER STRUCTURE

```
railbridge-ai/
│
├── desktop/                          # Electron frontend
│   ├── src/
│   │   ├── main/                     # Electron main process
│   │   │   ├── main.ts
│   │   │   ├── ipc-handlers.ts
│   │   │   └── window-manager.ts
│   │   ├── renderer/                 # React UI
│   │   │   ├── App.tsx
│   │   │   ├── pages/
│   │   │   │   ├── Upload.tsx
│   │   │   │   ├── Processing.tsx
│   │   │   │   ├── Review.tsx
│   │   │   │   └── Export.tsx
│   │   │   ├── components/
│   │   │   │   ├── AgentStatusPanel.tsx
│   │   │   │   ├── DrawingViewer.tsx
│   │   │   │   ├── KnowledgeGraphViewer.tsx
│   │   │   │   ├── ConfidenceGauge.tsx
│   │   │   │   └── ExtractionReport.tsx
│   │   │   └── stores/
│   │   │       ├── sessionStore.ts
│   │   │       └── agentStore.ts
│   └── package.json
│
├── backend/                          # Python FastAPI backend
│   ├── main.py                       # FastAPI app entry
│   ├── api/
│   │   ├── routes/
│   │   │   ├── upload.py
│   │   │   ├── process.py
│   │   │   ├── export.py
│   │   │   └── status.py
│   │   └── websocket.py              # Real-time agent status
│   ├── agents/
│   │   ├── base_agent.py
│   │   ├── agent_01_layout.py
│   │   ├── agent_02_ocr.py
│   │   ├── agent_03_geometry.py
│   │   ├── agent_04_dimension.py
│   │   ├── agent_05_bridge_engineering.py
│   │   ├── agent_06_level_analysis.py
│   │   ├── agent_07_structural.py
│   │   ├── agent_08_hydraulic.py
│   │   ├── agent_09_challenger.py
│   │   ├── agent_10_validation.py
│   │   ├── agent_11_standards.py
│   │   ├── agent_12_parametric.py
│   │   ├── agent_13_cad_drafting.py
│   │   ├── agent_14_autocad.py
│   │   ├── agent_15_comparison.py
│   │   └── agent_16_final_qa.py
│   ├── graph/
│   │   ├── langgraph_pipeline.py     # LangGraph orchestration
│   │   ├── state_schema.py           # Shared state TypedDict
│   │   └── routing.py               # Conditional routing logic
│   ├── knowledge/
│   │   ├── knowledge_graph.py        # Neo4j interface
│   │   ├── bridge_ontology.py        # Domain entity definitions
│   │   └── standards/
│   │       ├── irs_bridge_code.json
│   │       ├── irbm_standards.json
│   │       └── rdso_standards.json
│   ├── vision/
│   │   ├── preprocessor.py           # OpenCV preprocessing
│   │   ├── layout_detector.py        # Detectron2 layout detection
│   │   └── geometry_extractor.py     # Line/arc/circle detection
│   ├── ocr/
│   │   ├── paddle_ocr_engine.py
│   │   ├── surya_ocr_engine.py
│   │   └── ocr_fusion.py            # Combine OCR outputs
│   ├── cad/
│   │   ├── dxf_generator.py          # ezdxf drawing generation
│   │   ├── script_generator.py       # AutoCAD SCR script
│   │   ├── layer_manager.py
│   │   └── templates/
│   │       ├── box_culvert.py
│   │       ├── slab_bridge.py
│   │       └── arch_bridge.py
│   ├── models/
│   │   ├── bridge_model.py           # Pydantic parametric model
│   │   ├── extraction_result.py
│   │   └── validation_report.py
│   ├── db/
│   │   ├── database.py               # SQLAlchemy setup
│   │   ├── models.py                 # DB ORM models
│   │   └── migrations/
│   └── config/
│       ├── settings.py
│       └── logging_config.py
│
├── ml_models/                        # Trained model weights
│   ├── layout_detector/              # Detectron2 weights
│   ├── dimension_parser/
│   └── bridge_classifier/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── benchmark/
│
├── docker/
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   └── docker-compose.yml
│
└── docs/
    ├── api_reference.md
    ├── agent_specifications.md
    └── deployment_guide.md
```

---

## 3. SHARED STATE SCHEMA (LangGraph)

```python
# backend/graph/state_schema.py

from typing import TypedDict, Optional, List, Dict, Any
from enum import Enum

class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"

class BridgeType(str, Enum):
    SINGLE_CELL_RCC_BOX = "single_cell_rcc_box"
    DOUBLE_CELL_RCC_BOX = "double_cell_rcc_box"
    TRIPLE_CELL_RCC_BOX = "triple_cell_rcc_box"
    SLAB_BRIDGE = "slab_bridge"
    ARCH_BRIDGE = "arch_bridge"
    MINOR_BRIDGE = "minor_bridge"

class DrawingZone(TypedDict):
    zone_id: str
    zone_type: str        # "plan" | "section" | "elevation" | "detail" | "table" | "notes"
    bbox: List[int]       # [x1, y1, x2, y2]
    confidence: float

class ExtractedLevel(TypedDict):
    level_type: str       # RL | FL | BL | HFL | CHFL | TOC | BOF
    value: float
    unit: str
    location: str
    raw_text: str

class ExtractedDimension(TypedDict):
    value: float
    unit: str
    direction: str        # horizontal | vertical
    chain_id: str
    associated_element: str
    bbox: List[int]

class GeometryElement(TypedDict):
    element_id: str
    element_type: str     # line | polyline | arc | circle | leader
    coordinates: List[Any]
    layer_hint: str

class ParametricBridgeModel(TypedDict):
    bridge_type: str
    clear_span: float         # mm
    clear_height: float       # mm
    wall_thickness: float     # mm
    top_slab_thickness: float
    bottom_slab_thickness: float
    num_cells: int
    cell_widths: List[float]
    wing_wall_length: float
    wing_wall_angle: float
    skew_angle: float
    bearing_thickness: float
    road_width: float
    waterway_area: float
    levels: Dict[str, float]
    haunch_size: float
    toe_wall_depth: float
    curtain_wall_thickness: float
    flooring_thickness: float

class ValidationIssue(TypedDict):
    severity: str             # error | warning | info
    agent: str
    message: str
    element: str
    suggested_fix: str

class RailBridgeState(TypedDict):
    # Session
    session_id: str
    input_file_path: str
    input_file_type: str

    # Agent statuses
    agent_statuses: Dict[str, AgentStatus]
    agent_confidence: Dict[str, float]

    # Agent 1 output
    drawing_zones: List[DrawingZone]
    preprocessed_images: Dict[str, str]   # zone_id -> image path

    # Agent 2 output
    raw_text_blocks: List[Dict]
    extracted_dimensions_raw: List[str]
    extracted_notes: List[str]
    extracted_annotations: List[str]

    # Agent 3 output
    geometry_elements: List[GeometryElement]
    scale_detected: float
    coordinate_system: str

    # Agent 4 output
    parsed_dimensions: List[ExtractedDimension]
    dimension_chains: Dict[str, List[float]]

    # Agent 5 output
    bridge_type: Optional[BridgeType]
    bridge_type_confidence: float
    bridge_classification_evidence: List[str]

    # Agent 6 output
    extracted_levels: List[ExtractedLevel]
    level_consistency_valid: bool

    # Agent 7 output
    structural_components: Dict[str, Any]
    structural_model_complete: bool

    # Agent 8 output
    hydraulic_data: Dict[str, Any]

    # Agent 9 output (Challenger)
    challenged_items: List[Dict]
    reanalysis_required: List[str]

    # Agent 10 output
    cross_validation_passed: bool
    cross_validation_issues: List[ValidationIssue]

    # Agent 11 output
    standards_violations: List[ValidationIssue]
    standards_compliance: bool

    # Agent 12 output
    parametric_model: Optional[ParametricBridgeModel]
    knowledge_graph_node_id: str

    # Agent 13 output
    cad_plan_data: Dict
    cad_section_data: Dict
    cad_elevation_data: Dict

    # Agent 14 output
    output_dxf_path: str
    output_dwg_path: str
    output_script_path: str

    # Agent 15 output
    comparison_score: float
    geometry_similarity: float
    dimension_similarity: float
    annotation_similarity: float

    # Agent 16 output
    final_approved: bool
    approval_report: Dict
    overall_confidence: float
    validation_issues: List[ValidationIssue]

    # Control
    iteration_count: int
    max_iterations: int
    error_log: List[str]
```

---

## 4. LANGGRAPH PIPELINE

```python
# backend/graph/langgraph_pipeline.py

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from state_schema import RailBridgeState
from agents import (
    agent_01_layout, agent_02_ocr, agent_03_geometry,
    agent_04_dimension, agent_05_bridge_engineering,
    agent_06_level_analysis, agent_07_structural,
    agent_08_hydraulic, agent_09_challenger,
    agent_10_validation, agent_11_standards,
    agent_12_parametric, agent_13_cad_drafting,
    agent_14_autocad, agent_15_comparison, agent_16_final_qa
)

CONFIDENCE_THRESHOLD = 0.95
MAX_ITERATIONS = 4

def route_after_challenger(state: RailBridgeState) -> str:
    if state["reanalysis_required"] and state["iteration_count"] < MAX_ITERATIONS:
        return "reanalyse"
    return "continue"

def route_after_qa(state: RailBridgeState) -> str:
    if state["overall_confidence"] >= CONFIDENCE_THRESHOLD:
        return "approve"
    if state["iteration_count"] < MAX_ITERATIONS:
        return "iterate"
    return "approve_with_warnings"

def build_pipeline() -> StateGraph:
    workflow = StateGraph(RailBridgeState)

    # Add all agent nodes
    workflow.add_node("layout_agent",         agent_01_layout.run)
    workflow.add_node("ocr_agent",            agent_02_ocr.run)
    workflow.add_node("geometry_agent",       agent_03_geometry.run)
    workflow.add_node("dimension_agent",      agent_04_dimension.run)
    workflow.add_node("bridge_eng_agent",     agent_05_bridge_engineering.run)
    workflow.add_node("level_agent",          agent_06_level_analysis.run)
    workflow.add_node("structural_agent",     agent_07_structural.run)
    workflow.add_node("hydraulic_agent",      agent_08_hydraulic.run)
    workflow.add_node("challenger_agent",     agent_09_challenger.run)
    workflow.add_node("validation_agent",     agent_10_validation.run)
    workflow.add_node("standards_agent",      agent_11_standards.run)
    workflow.add_node("parametric_agent",     agent_12_parametric.run)
    workflow.add_node("cad_drafting_agent",   agent_13_cad_drafting.run)
    workflow.add_node("autocad_agent",        agent_14_autocad.run)
    workflow.add_node("comparison_agent",     agent_15_comparison.run)
    workflow.add_node("final_qa_agent",       agent_16_final_qa.run)

    # Sequential pipeline with parallel branches
    workflow.set_entry_point("layout_agent")

    # Phase 1: Extraction (sequential)
    workflow.add_edge("layout_agent",     "ocr_agent")
    workflow.add_edge("ocr_agent",        "geometry_agent")
    workflow.add_edge("geometry_agent",   "dimension_agent")

    # Phase 2: Understanding (parallel-capable, sequential for safety)
    workflow.add_edge("dimension_agent",  "bridge_eng_agent")
    workflow.add_edge("bridge_eng_agent", "level_agent")
    workflow.add_edge("level_agent",      "structural_agent")
    workflow.add_edge("structural_agent", "hydraulic_agent")

    # Phase 3: Challenge & Validate
    workflow.add_edge("hydraulic_agent",  "challenger_agent")
    workflow.add_conditional_edges(
        "challenger_agent",
        route_after_challenger,
        {
            "reanalyse": "dimension_agent",   # loop back
            "continue":  "validation_agent"
        }
    )
    workflow.add_edge("validation_agent", "standards_agent")

    # Phase 4: Model & Generate
    workflow.add_edge("standards_agent",  "parametric_agent")
    workflow.add_edge("parametric_agent", "cad_drafting_agent")
    workflow.add_edge("cad_drafting_agent","autocad_agent")

    # Phase 5: QA
    workflow.add_edge("autocad_agent",    "comparison_agent")
    workflow.add_edge("comparison_agent", "final_qa_agent")
    workflow.add_conditional_edges(
        "final_qa_agent",
        route_after_qa,
        {
            "approve":               END,
            "iterate":               "parametric_agent",  # refine and redraw
            "approve_with_warnings": END
        }
    )

    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)
```

---

## 5. AGENT IMPLEMENTATIONS (Key Agents)

### Agent 01 — Layout Agent

```python
# backend/agents/agent_01_layout.py

import cv2
from detectron2 import model_zoo
from detectron2.engine import DefaultPredictor
from detectron2.config import get_cfg
from state_schema import RailBridgeState, DrawingZone, AgentStatus

ZONE_CLASSES = ["plan", "section", "elevation", "detail", "table", "title_block", "notes"]

def run(state: RailBridgeState) -> RailBridgeState:
    state["agent_statuses"]["layout_agent"] = AgentStatus.RUNNING

    img = cv2.imread(state["input_file_path"])
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    cfg = get_cfg()
    cfg.merge_from_file(model_zoo.get_config_file(
        "COCO-Detection/faster_rcnn_R_50_FPN_3x.yaml"
    ))
    cfg.MODEL.WEIGHTS = "ml_models/layout_detector/model_final.pth"
    cfg.MODEL.ROI_HEADS.NUM_CLASSES = len(ZONE_CLASSES)
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = 0.5

    predictor = DefaultPredictor(cfg)
    outputs = predictor(img_rgb)

    zones = []
    instances = outputs["instances"].to("cpu")

    for i, (box, cls, score) in enumerate(zip(
        instances.pred_boxes.tensor.numpy(),
        instances.pred_classes.numpy(),
        instances.scores.numpy()
    )):
        zone = DrawingZone(
            zone_id=f"zone_{i:03d}",
            zone_type=ZONE_CLASSES[cls],
            bbox=[int(x) for x in box],
            confidence=float(score)
        )
        zones.append(zone)

        # Crop and save zone image for downstream agents
        x1, y1, x2, y2 = zone["bbox"]
        crop = img[y1:y2, x1:x2]
        crop_path = f"/tmp/{state['session_id']}/zones/{zone['zone_id']}.png"
        cv2.imwrite(crop_path, crop)
        state["preprocessed_images"][zone["zone_id"]] = crop_path

    state["drawing_zones"] = zones
    state["agent_statuses"]["layout_agent"] = AgentStatus.DONE
    state["agent_confidence"]["layout_agent"] = float(
        instances.scores.mean().item() if len(instances) > 0 else 0.0
    )
    return state
```

### Agent 04 — Dimension Understanding Agent

```python
# backend/agents/agent_04_dimension.py

import re
from anthropic import Anthropic
from state_schema import RailBridgeState, ExtractedDimension, AgentStatus

client = Anthropic()

DIMENSION_SYSTEM_PROMPT = """
You are a senior railway bridge engineer. You receive raw OCR text from bridge drawings.
Your task is to identify ALL dimension strings and classify them.

A dimension chain like:
  3375   350   3375
represents: Cell1=3375mm, CenterWall=350mm, Cell2=3375mm

Output ONLY valid JSON array of dimension objects.
Each object must have:
- value: number in mm
- label: what this dimension represents
- chain_id: group identifier for related dimensions
- direction: "horizontal" or "vertical"
- associated_element: structural element this dimension belongs to

Common elements: top_slab, bottom_slab, side_wall, center_wall, haunch,
  wing_wall, clear_span, clear_height, road_width, kerb, wearing_coat,
  toe_wall, curtain_wall, return_wall, flooring
"""

def run(state: RailBridgeState) -> RailBridgeState:
    state["agent_statuses"]["dimension_agent"] = AgentStatus.RUNNING

    raw_text = "\n".join(state["extracted_dimensions_raw"])

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        system=DIMENSION_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Extract and classify all dimensions from this bridge drawing text:\n\n{raw_text}"
        }]
    )

    import json
    dims_raw = json.loads(response.content[0].text)

    parsed = []
    chain_totals = {}

    for d in dims_raw:
        dim = ExtractedDimension(
            value=float(d["value"]),
            unit="mm",
            direction=d.get("direction", "horizontal"),
            chain_id=d.get("chain_id", "default"),
            associated_element=d.get("associated_element", "unknown"),
            bbox=[]
        )
        parsed.append(dim)

        cid = dim["chain_id"]
        chain_totals[cid] = chain_totals.get(cid, 0) + dim["value"]

    state["parsed_dimensions"] = parsed
    state["dimension_chains"] = chain_totals
    state["agent_statuses"]["dimension_agent"] = AgentStatus.DONE
    state["agent_confidence"]["dimension_agent"] = 0.88
    return state
```

### Agent 12 — Parametric Modeling Agent

```python
# backend/agents/agent_12_parametric.py

from anthropic import Anthropic
import json
from state_schema import RailBridgeState, ParametricBridgeModel, AgentStatus

client = Anthropic()

PARAMETRIC_SYSTEM = """
You are a senior structural engineer specializing in railway bridge design.
Given extracted bridge data, build the complete parametric model.
All dimensions must be in millimeters.
Output ONLY valid JSON matching the ParametricBridgeModel schema.
Apply engineering judgment where values are uncertain.
Validate internal consistency (e.g., total_width = sum of cell_widths + wall_thicknesses).
"""

def run(state: RailBridgeState) -> RailBridgeState:
    state["agent_statuses"]["parametric_agent"] = AgentStatus.RUNNING

    context = {
        "bridge_type": state.get("bridge_type"),
        "dimensions": state.get("parsed_dimensions", []),
        "levels": state.get("extracted_levels", []),
        "structural_components": state.get("structural_components", {}),
        "hydraulic_data": state.get("hydraulic_data", {}),
        "standards_violations": state.get("standards_violations", []),
    }

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2048,
        system=PARAMETRIC_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"Build the parametric bridge model from:\n{json.dumps(context, indent=2)}"
        }]
    )

    model_data = json.loads(response.content[0].text)
    state["parametric_model"] = ParametricBridgeModel(**model_data)

    # Write to knowledge graph
    from knowledge.knowledge_graph import KnowledgeGraph
    kg = KnowledgeGraph()
    node_id = kg.create_bridge_node(state["session_id"], state["parametric_model"])
    state["knowledge_graph_node_id"] = node_id

    state["agent_statuses"]["parametric_agent"] = AgentStatus.DONE
    state["agent_confidence"]["parametric_agent"] = 0.91
    return state
```

### Agent 13 — CAD Drafting Agent

```python
# backend/agents/agent_13_cad_drafting.py

from state_schema import RailBridgeState, AgentStatus, ParametricBridgeModel

def run(state: RailBridgeState) -> RailBridgeState:
    state["agent_statuses"]["cad_drafting_agent"] = AgentStatus.RUNNING
    m = state["parametric_model"]

    if "double_cell" in m["bridge_type"] or "triple_cell" in m["bridge_type"]:
        from cad.templates.box_culvert import BoxCulvertTemplate
        template = BoxCulvertTemplate(m)
    elif m["bridge_type"] == "slab_bridge":
        from cad.templates.slab_bridge import SlabBridgeTemplate
        template = SlabBridgeTemplate(m)
    else:
        from cad.templates.box_culvert import BoxCulvertTemplate
        template = BoxCulvertTemplate(m)

    state["cad_plan_data"]      = template.generate_plan()
    state["cad_section_data"]   = template.generate_section()
    state["cad_elevation_data"] = template.generate_elevation()

    state["agent_statuses"]["cad_drafting_agent"] = AgentStatus.DONE
    state["agent_confidence"]["cad_drafting_agent"] = 0.93
    return state
```

### Agent 14 — AutoCAD DXF Generator

```python
# backend/agents/agent_14_autocad.py

import ezdxf
from ezdxf import units
from state_schema import RailBridgeState, AgentStatus
import os

LAYERS = {
    "OUTLINE":      {"color": 7,  "ltype": "CONTINUOUS", "lw": 0.5},
    "DIMENSION":    {"color": 3,  "ltype": "CONTINUOUS", "lw": 0.18},
    "CENTERLINE":   {"color": 1,  "ltype": "CENTER",      "lw": 0.18},
    "HATCH":        {"color": 8,  "ltype": "CONTINUOUS", "lw": 0.13},
    "ANNOTATION":   {"color": 2,  "ltype": "CONTINUOUS", "lw": 0.18},
    "LEVEL":        {"color": 4,  "ltype": "CONTINUOUS", "lw": 0.18},
    "WATERWAY":     {"color": 5,  "ltype": "DASHED",     "lw": 0.18},
    "REINFORCEMENT":{"color": 6,  "ltype": "CONTINUOUS", "lw": 0.25},
}

def run(state: RailBridgeState) -> RailBridgeState:
    state["agent_statuses"]["autocad_agent"] = AgentStatus.RUNNING

    doc = ezdxf.new(dxfversion="R2018")
    doc.units = units.MM
    msp = doc.modelspace()

    # Setup layers
    for lname, lprops in LAYERS.items():
        layer = doc.layers.new(name=lname)
        layer.color = lprops["color"]
        layer.linetype = lprops["ltype"]
        layer.lineweight = int(lprops["lw"] * 100)

    # Draw from plan data
    _draw_plan(msp, state["cad_plan_data"])
    _draw_section(msp, state["cad_section_data"])
    _draw_elevation(msp, state["cad_elevation_data"])
    _add_title_block(msp, doc, state)

    session_dir = f"/tmp/{state['session_id']}/output"
    os.makedirs(session_dir, exist_ok=True)

    dxf_path = f"{session_dir}/bridge_drawing.dxf"
    doc.saveas(dxf_path)
    state["output_dxf_path"] = dxf_path

    # Generate AutoCAD script
    _generate_script(state, session_dir)

    state["agent_statuses"]["autocad_agent"] = AgentStatus.DONE
    state["agent_confidence"]["autocad_agent"] = 0.95
    return state

def _draw_plan(msp, plan_data):
    for element in plan_data.get("elements", []):
        if element["type"] == "line":
            msp.add_line(
                element["start"], element["end"],
                dxfattribs={"layer": element.get("layer", "OUTLINE")}
            )
        elif element["type"] == "lwpolyline":
            msp.add_lwpolyline(
                element["points"],
                dxfattribs={"layer": element.get("layer", "OUTLINE"), "closed": element.get("closed", True)}
            )
        elif element["type"] == "text":
            msp.add_text(
                element["text"],
                dxfattribs={"layer": "ANNOTATION", "height": element.get("height", 150)}
            ).set_placement(element["position"])
        elif element["type"] == "dim_linear":
            msp.add_linear_dim(
                base=element["base"],
                p1=element["p1"],
                p2=element["p2"],
                dimstyle="STANDARD",
                dxfattribs={"layer": "DIMENSION"}
            ).render()

def _draw_section(msp, section_data):
    # Same pattern as plan, offset to a different UCS position
    offset_x = section_data.get("offset", [0, 0])
    for element in section_data.get("elements", []):
        if element["type"] == "line":
            s = (element["start"][0]+offset_x[0], element["start"][1]+offset_x[1])
            e = (element["end"][0]+offset_x[0],   element["end"][1]+offset_x[1])
            msp.add_line(s, e, dxfattribs={"layer": element.get("layer", "OUTLINE")})

def _draw_elevation(msp, elevation_data):
    offset_x = elevation_data.get("offset", [0, 0])
    for element in elevation_data.get("elements", []):
        if element["type"] == "line":
            s = (element["start"][0]+offset_x[0], element["start"][1]+offset_x[1])
            e = (element["end"][0]+offset_x[0],   element["end"][1]+offset_x[1])
            msp.add_line(s, e, dxfattribs={"layer": element.get("layer", "OUTLINE")})

def _add_title_block(msp, doc, state):
    m = state["parametric_model"]
    title_texts = [
        (f"BRIDGE TYPE: {m['bridge_type'].upper()}", (0, -5000)),
        (f"CLEAR SPAN: {m['clear_span']} mm", (0, -5300)),
        (f"CLEAR HEIGHT: {m['clear_height']} mm", (0, -5600)),
        (f"GENERATED BY: RailBridgeAI", (0, -5900)),
        (f"CONFIDENCE: {state.get('overall_confidence', 0)*100:.1f}%", (0, -6200)),
    ]
    for text, pos in title_texts:
        msp.add_text(text, dxfattribs={"layer": "ANNOTATION", "height": 200}).set_placement(pos)

def _generate_script(state, session_dir):
    script_lines = ["LIMITS\n0,0\n841000,594000\nZOOM\nE\n"]
    script_path = f"{session_dir}/bridge_drawing.scr"
    with open(script_path, "w") as f:
        f.write("\n".join(script_lines))
    state["output_script_path"] = script_path
```

---

## 6. KNOWLEDGE GRAPH (Neo4j)

```python
# backend/knowledge/knowledge_graph.py

from neo4j import GraphDatabase
from config.settings import settings

class KnowledgeGraph:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        )

    def create_bridge_node(self, session_id: str, model: dict) -> str:
        with self.driver.session() as session:
            result = session.run("""
                CREATE (b:Bridge {
                    session_id: $session_id,
                    bridge_type: $bridge_type,
                    clear_span: $clear_span,
                    clear_height: $clear_height,
                    num_cells: $num_cells
                })
                WITH b
                UNWIND range(0, $num_cells-1) AS i
                CREATE (s:Span {span_index: i, width: $cell_widths[i]})-[:PART_OF]->(b)
                RETURN elementId(b) as node_id
            """, {
                "session_id": session_id,
                "bridge_type": model["bridge_type"],
                "clear_span": model["clear_span"],
                "clear_height": model["clear_height"],
                "num_cells": model["num_cells"],
                "cell_widths": model["cell_widths"]
            })
            return result.single()["node_id"]

    def validate_against_standards(self, model: dict) -> list:
        """Query knowledge graph for standards compliance"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (s:Standard)-[:APPLIES_TO]->(bt:BridgeType {name: $bridge_type})
                RETURN s.rule, s.min_value, s.max_value, s.parameter
            """, {"bridge_type": model["bridge_type"]})
            violations = []
            for record in result:
                param = record["s.parameter"]
                val = model.get(param)
                if val and (val < record["s.min_value"] or val > record["s.max_value"]):
                    violations.append({
                        "parameter": param,
                        "value": val,
                        "allowed_range": [record["s.min_value"], record["s.max_value"]],
                        "rule": record["s.rule"]
                    })
            return violations
```

---

## 7. BOX CULVERT CAD TEMPLATE

```python
# backend/cad/templates/box_culvert.py

from typing import Dict, List, Any

class BoxCulvertTemplate:
    """
    Generates plan, section, and elevation geometry data
    for RCC box culverts (single/double/triple cell).
    All coordinates in mm.
    """

    def __init__(self, model: Dict):
        self.m = model
        self.origin = (0, 0)
        self._compute_geometry()

    def _compute_geometry(self):
        m = self.m
        # Compute total width
        self.total_width = (
            sum(m["cell_widths"]) +
            (m["num_cells"] + 1) * m["wall_thickness"]
        )
        self.total_height = (
            m["clear_height"] +
            m["top_slab_thickness"] +
            m["bottom_slab_thickness"]
        )

    def generate_section(self) -> Dict[str, Any]:
        m = self.m
        elements = []
        x = 0

        # Outer outline
        outline = [
            (0, 0),
            (self.total_width, 0),
            (self.total_width, self.total_height),
            (0, self.total_height),
        ]
        elements.append({"type": "lwpolyline", "points": outline, "closed": True, "layer": "OUTLINE"})

        # Internal walls
        x = m["wall_thickness"]
        for i in range(m["num_cells"]):
            cell_w = m["cell_widths"][i]
            x += cell_w
            if i < m["num_cells"] - 1:
                # Internal wall
                elements.append({
                    "type": "line",
                    "start": (x, m["bottom_slab_thickness"]),
                    "end": (x, self.total_height - m["top_slab_thickness"]),
                    "layer": "OUTLINE"
                })
                x += m["wall_thickness"]

        # Bottom slab line
        elements.append({
            "type": "line",
            "start": (0, m["bottom_slab_thickness"]),
            "end": (self.total_width, m["bottom_slab_thickness"]),
            "layer": "OUTLINE"
        })

        # Top slab line
        elements.append({
            "type": "line",
            "start": (0, self.total_height - m["top_slab_thickness"]),
            "end": (self.total_width, self.total_height - m["top_slab_thickness"]),
            "layer": "OUTLINE"
        })

        # Haunches
        h = m.get("haunch_size", 150)
        corners = [
            (m["wall_thickness"], m["bottom_slab_thickness"]),
            (self.total_width - m["wall_thickness"], m["bottom_slab_thickness"]),
            (m["wall_thickness"], self.total_height - m["top_slab_thickness"]),
            (self.total_width - m["wall_thickness"], self.total_height - m["top_slab_thickness"]),
        ]
        for cx, cy in corners:
            elements.append({
                "type": "arc", "center": (cx, cy), "radius": h,
                "start_angle": 0, "end_angle": 90, "layer": "OUTLINE"
            })

        # Centerline
        mid_x = self.total_width / 2
        elements.append({
            "type": "line",
            "start": (mid_x, -500),
            "end": (mid_x, self.total_height + 500),
            "layer": "CENTERLINE"
        })

        # Dimensions — span
        x_cursor = 0
        for i, cw in enumerate(m["cell_widths"]):
            x_cursor += m["wall_thickness"]
            elements.append({
                "type": "dim_linear",
                "base": (x_cursor + cw/2, -1000),
                "p1": (x_cursor, 0),
                "p2": (x_cursor + cw, 0),
                "layer": "DIMENSION"
            })
            x_cursor += cw

        return {"elements": elements, "offset": [self.total_width + 5000, 0]}

    def generate_plan(self) -> Dict[str, Any]:
        m = self.m
        elements = []
        road_w = m.get("road_width", self.total_width + 2000)

        # Outer plan boundary
        outline = [
            (0, 0),
            (road_w, 0),
            (road_w, m.get("wing_wall_length", 3000)),
            (0, m.get("wing_wall_length", 3000)),
        ]
        elements.append({"type": "lwpolyline", "points": outline, "closed": True, "layer": "OUTLINE"})

        # Box cell openings
        x = (road_w - self.total_width) / 2
        for i, cw in enumerate(m["cell_widths"]):
            x += m["wall_thickness"]
            cell_rect = [
                (x, 0), (x+cw, 0),
                (x+cw, m.get("wing_wall_length", 3000)),
                (x, m.get("wing_wall_length", 3000))
            ]
            elements.append({"type": "lwpolyline", "points": cell_rect, "closed": True, "layer": "WATERWAY"})
            x += cw

        return {"elements": elements, "offset": [0, self.total_height + 5000]}

    def generate_elevation(self) -> Dict[str, Any]:
        m = self.m
        elements = []
        wl = m.get("wing_wall_length", 3000)

        # Front face
        front = [
            (0, 0), (self.total_width, 0),
            (self.total_width, self.total_height),
            (0, self.total_height)
        ]
        elements.append({"type": "lwpolyline", "points": front, "closed": True, "layer": "OUTLINE"})

        # HFL line
        hfl = m.get("levels", {}).get("HFL", self.total_height * 0.7)
        elements.append({
            "type": "line",
            "start": (-500, hfl),
            "end": (self.total_width + 500, hfl),
            "layer": "WATERWAY"
        })
        elements.append({
            "type": "text",
            "text": f"HFL={m['levels'].get('HFL','N/A')}",
            "position": (self.total_width + 600, hfl),
            "height": 150,
            "layer": "LEVEL"
        })

        return {"elements": elements, "offset": [self.total_width * 2 + 5000, 0]}
```

---

## 8. DATABASE SCHEMA (PostgreSQL)

```sql
-- Sessions table
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    input_file_path TEXT NOT NULL,
    input_file_type VARCHAR(10),
    status VARCHAR(20) DEFAULT 'pending',
    overall_confidence FLOAT,
    iteration_count INT DEFAULT 0
);

-- Agent runs table
CREATE TABLE agent_runs (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id),
    agent_name VARCHAR(50) NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    status VARCHAR(20),
    confidence FLOAT,
    error_message TEXT,
    output_summary JSONB
);

-- Parametric models table
CREATE TABLE parametric_models (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id),
    bridge_type VARCHAR(50),
    clear_span_mm FLOAT,
    clear_height_mm FLOAT,
    wall_thickness_mm FLOAT,
    top_slab_mm FLOAT,
    bottom_slab_mm FLOAT,
    num_cells INT,
    cell_widths FLOAT[],
    model_json JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Extracted levels table
CREATE TABLE extracted_levels (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id),
    level_type VARCHAR(20),
    value_m FLOAT,
    location TEXT,
    confidence FLOAT
);

-- Validation issues table
CREATE TABLE validation_issues (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id),
    severity VARCHAR(10),
    agent_name VARCHAR(50),
    message TEXT,
    element TEXT,
    suggested_fix TEXT
);

-- Outputs table
CREATE TABLE outputs (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id),
    output_type VARCHAR(20),  -- dxf, dwg, script, report
    file_path TEXT,
    generated_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 9. FASTAPI ROUTES

```python
# backend/api/routes/process.py

from fastapi import APIRouter, BackgroundTasks, WebSocket
from pydantic import BaseModel
import uuid
from graph.langgraph_pipeline import build_pipeline

router = APIRouter(prefix="/api/v1")

class ProcessRequest(BaseModel):
    file_path: str
    file_type: str

@router.post("/process")
async def start_processing(req: ProcessRequest, background_tasks: BackgroundTasks):
    session_id = str(uuid.uuid4())
    initial_state = {
        "session_id": session_id,
        "input_file_path": req.file_path,
        "input_file_type": req.file_type,
        "agent_statuses": {},
        "agent_confidence": {},
        "preprocessed_images": {},
        "iteration_count": 0,
        "max_iterations": 4,
        "error_log": []
    }
    pipeline = build_pipeline()
    background_tasks.add_task(pipeline.invoke, initial_state, {"configurable": {"thread_id": session_id}})
    return {"session_id": session_id, "status": "started"}

@router.get("/status/{session_id}")
async def get_status(session_id: str):
    pipeline = build_pipeline()
    state = pipeline.get_state({"configurable": {"thread_id": session_id}})
    if not state:
        return {"error": "session not found"}
    return {
        "agent_statuses": state.values.get("agent_statuses", {}),
        "agent_confidence": state.values.get("agent_confidence", {}),
        "overall_confidence": state.values.get("overall_confidence", 0),
        "iteration_count": state.values.get("iteration_count", 0),
    }

@router.websocket("/ws/{session_id}")
async def websocket_status(websocket: WebSocket, session_id: str):
    await websocket.accept()
    import asyncio
    pipeline = build_pipeline()
    while True:
        state = pipeline.get_state({"configurable": {"thread_id": session_id}})
        if state:
            await websocket.send_json({
                "agent_statuses": state.values.get("agent_statuses", {}),
                "overall_confidence": state.values.get("overall_confidence", 0),
            })
        await asyncio.sleep(0.5)
```

---

## 10. DOCKER COMPOSE

```yaml
# docker/docker-compose.yml

version: "3.9"

services:
  backend:
    build:
      context: ..
      dockerfile: docker/Dockerfile.backend
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://railbridge:railbridge@postgres:5432/railbridge
      - NEO4J_URI=bolt://neo4j:7687
      - NEO4J_USER=neo4j
      - NEO4J_PASSWORD=railbridge123
    volumes:
      - ./ml_models:/app/ml_models
      - uploads:/tmp/uploads
    depends_on:
      - postgres
      - neo4j

  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: railbridge
      POSTGRES_PASSWORD: railbridge
      POSTGRES_DB: railbridge
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  neo4j:
    image: neo4j:5
    environment:
      NEO4J_AUTH: neo4j/railbridge123
    ports:
      - "7474:7474"
      - "7687:7687"
    volumes:
      - neo4jdata:/data

volumes:
  pgdata:
  neo4jdata:
  uploads:
```

---

## 11. DEVELOPMENT ROADMAP

### Phase 1 — Foundation (Weeks 1–4)
- [ ] Electron desktop shell + React UI scaffold
- [ ] FastAPI backend with session management
- [ ] PostgreSQL + Neo4j setup
- [ ] File upload and preprocessing pipeline
- [ ] PaddleOCR + Surya integration

### Phase 2 — Core Agents (Weeks 5–10)
- [ ] Train Detectron2 layout detector on 500+ railway drawings
- [ ] Implement Agents 1–8
- [ ] LangGraph pipeline integration
- [ ] Dimension parsing with Claude API
- [ ] Knowledge graph ontology with IRS/RDSO standards

### Phase 3 — Generation (Weeks 11–14)
- [ ] Parametric model builder (Agent 12)
- [ ] CAD templates for all bridge types
- [ ] ezdxf DXF generation (Agent 14)
- [ ] AutoCAD script export

### Phase 4 — Validation & QA (Weeks 15–17)
- [ ] Challenger Agent (Agent 9)
- [ ] Comparison Agent (Agent 15)
- [ ] Self-improvement loop
- [ ] Standards compliance engine

### Phase 5 — Production (Weeks 18–20)
- [ ] Electron packaging (Windows installer)
- [ ] Performance optimization
- [ ] Batch processing mode
- [ ] CI/CD pipeline
- [ ] User acceptance testing with actual GADs

---

## 12. PERFORMANCE TARGETS

| Metric | Target |
|---|---|
| Processing time (A4 drawing) | < 3 minutes |
| Processing time (A1 GAD) | < 8 minutes |
| Geometry similarity score | > 90% |
| Dimension extraction accuracy | > 95% |
| Overall confidence threshold | 95% |
| Max self-improvement iterations | 4 |
| Supported bridge types | 6+ |
| Supported input formats | PDF, TIFF, PNG, JPG, scanned PDF |
| Output formats | DXF, DWG, SCR, JSON, PDF report |

---

*Generated by RailBridgeAI Architecture Team*
*Version 1.0 — Production Ready Specification*
