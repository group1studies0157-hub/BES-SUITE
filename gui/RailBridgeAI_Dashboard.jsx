import { useState, useEffect, useRef } from "react";

// ─── Color palette & design tokens ───────────────────────────────────────────
const C = {
  bg:        "#0a0c10",
  surface:   "#111318",
  card:      "#161920",
  border:    "#1e2330",
  accent:    "#f5a623",
  accentDim: "#7a5010",
  blue:      "#3d8ef0",
  green:     "#22c55e",
  red:       "#ef4444",
  yellow:    "#facc15",
  muted:     "#4a5568",
  text:      "#e2e8f0",
  textDim:   "#64748b",
  rail:      "#f5a623",
};

const AGENTS = [
  { id: "layout_agent",        num: "01", label: "Drawing Layout",       phase: 1, desc: "Detects plans, sections, elevations, tables, title block" },
  { id: "ocr_agent",           num: "02", label: "OCR Extraction",        phase: 1, desc: "Extracts all text, dimensions, annotations, notes, levels" },
  { id: "geometry_agent",      num: "03", label: "Geometry Detection",    phase: 1, desc: "Detects lines, polylines, arcs, circles, leaders" },
  { id: "dimension_agent",     num: "04", label: "Dimension Understanding",phase: 1, desc: "Associates dimensions with structural elements" },
  { id: "bridge_eng_agent",    num: "05", label: "Bridge Engineering",    phase: 2, desc: "Identifies bridge type and builds engineering understanding" },
  { id: "level_agent",         num: "06", label: "Level Analysis",        phase: 2, desc: "Extracts RL, FL, BL, HFL, CHFL, TOC, BOF values" },
  { id: "structural_agent",    num: "07", label: "Structural Understanding",phase: 2, desc: "Maps top slab, bottom slab, walls, wing walls" },
  { id: "hydraulic_agent",     num: "08", label: "Hydraulic Analysis",    phase: 2, desc: "Extracts waterway, velocity, discharge, freeboard" },
  { id: "challenger_agent",    num: "09", label: "Challenger",            phase: 3, desc: "Challenges all conclusions, forces re-analysis on low confidence" },
  { id: "validation_agent",    num: "10", label: "Cross Validation",      phase: 3, desc: "Cross-checks Plan vs Section vs Elevation consistency" },
  { id: "standards_agent",     num: "11", label: "Standards Compliance",  phase: 3, desc: "Validates against IRS Bridge Code, IRBM, RDSO" },
  { id: "parametric_agent",    num: "12", label: "Parametric Modeling",   phase: 4, desc: "Creates the engineering digital twin model" },
  { id: "cad_drafting_agent",  num: "13", label: "CAD Drafting",          phase: 4, desc: "Generates plan, elevation, section geometry" },
  { id: "autocad_agent",       num: "14", label: "AutoCAD Output",        phase: 4, desc: "Generates DWG, DXF, AutoCAD Script" },
  { id: "comparison_agent",    num: "15", label: "Drawing Comparison",    phase: 5, desc: "Compares generated vs source drawing" },
  { id: "final_qa_agent",      num: "16", label: "Final QA",             phase: 5, desc: "Performs final engineering review and approval" },
];

const PHASES = [
  { id: 1, label: "EXTRACTION",   color: "#3d8ef0" },
  { id: 2, label: "UNDERSTANDING",color: "#a855f7" },
  { id: 3, label: "VALIDATION",   color: "#f97316" },
  { id: 4, label: "GENERATION",   color: "#22c55e" },
  { id: 5, label: "QA & EXPORT",  color: C.accent  },
];

const STATUS_COLOR = { pending: C.muted, running: C.blue, done: C.green, failed: C.red, skipped: C.yellow };
const STATUS_ICON  = { pending: "○", running: "◉", done: "✓", failed: "✗", skipped: "⊘" };

// ─── Simulation logic ─────────────────────────────────────────────────────────
function useSimulation(active) {
  const [statuses, setStatuses] = useState(() =>
    Object.fromEntries(AGENTS.map(a => [a.id, "pending"]))
  );
  const [confidences, setConfidences] = useState(() =>
    Object.fromEntries(AGENTS.map(a => [a.id, 0]))
  );
  const [overallConf, setOverallConf] = useState(0);
  const [iteration, setIteration] = useState(0);
  const [currentMsg, setCurrentMsg] = useState("");
  const [complete, setComplete] = useState(false);
  const timerRef = useRef(null);

  const AGENT_CONF = {
    layout_agent: 0.91, ocr_agent: 0.87, geometry_agent: 0.89,
    dimension_agent: 0.88, bridge_eng_agent: 0.94, level_agent: 0.92,
    structural_agent: 0.90, hydraulic_agent: 0.86, challenger_agent: 0.95,
    validation_agent: 0.93, standards_agent: 0.97, parametric_agent: 0.91,
    cad_drafting_agent: 0.93, autocad_agent: 0.95, comparison_agent: 0.88, final_qa_agent: 0.96,
  };

  const MSGS = [
    "Preprocessing scanned drawing…",
    "Detecting title block and drawing zones…",
    "Running PaddleOCR on all zones…",
    "Extracting vector geometry via OpenCV…",
    "Parsing dimension chains (3375 | 350 | 3375)…",
    "Classifying bridge type: Double Cell RCC Box…",
    "Extracting levels: RL=100.850, HFL=101.200…",
    "Building structural component map…",
    "Validating hydraulic data: Q=2.4 m³/s…",
    "Challenger Agent: Flagging low-confidence dimension…",
    "Re-analysing dimension chain in Section view…",
    "Cross-validating Plan vs Section vs Elevation…",
    "Checking IRS Bridge Code compliance…",
    "Building parametric model: clear_span=3375mm…",
    "Generating DXF geometry from parametric model…",
    "Writing AutoCAD DXF (R2018 format)…",
    "Comparing generated vs source drawing…",
    "Final QA: Confidence 96.2% — APPROVED ✓",
  ];

  useEffect(() => {
    if (!active) return;
    let i = 0;
    let msgIdx = 0;
    const runNext = () => {
      if (i >= AGENTS.length) {
        setOverallConf(0.962);
        setComplete(true);
        setCurrentMsg("Pipeline complete — Drawing approved ✓");
        return;
      }
      const agent = AGENTS[i];
      setStatuses(s => ({ ...s, [agent.id]: "running" }));
      setCurrentMsg(MSGS[msgIdx] || `Running ${agent.label}…`);
      msgIdx++;

      const delay = 700 + Math.random() * 800;
      timerRef.current = setTimeout(() => {
        const conf = AGENT_CONF[agent.id] + (Math.random() - 0.5) * 0.04;
        setStatuses(s => ({ ...s, [agent.id]: conf < 0.7 ? "failed" : "done" }));
        setConfidences(c => ({ ...c, [agent.id]: Math.max(0, Math.min(1, conf)) }));
        setOverallConf(prev => {
          const done = i + 1;
          return (prev * i + conf) / done;
        });

        // Challenger triggers re-analysis at agent 9
        if (agent.id === "challenger_agent" && iteration === 0) {
          setIteration(1);
          setCurrentMsg(MSGS[msgIdx] || "Challenger forcing re-analysis…");
          msgIdx++;
        }
        i++;
        timerRef.current = setTimeout(runNext, 200);
      }, delay);
    };

    timerRef.current = setTimeout(runNext, 600);
    return () => clearTimeout(timerRef.current);
  }, [active]);

  return { statuses, confidences, overallConf, iteration, currentMsg, complete };
}

// ─── Confidence Ring ──────────────────────────────────────────────────────────
function ConfidenceRing({ value, size = 120, label }) {
  const r = (size - 16) / 2;
  const circ = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(1, value));
  const dash = pct * circ;
  const color = pct >= 0.95 ? C.green : pct >= 0.80 ? C.accent : C.red;

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={C.border} strokeWidth={8} />
        <circle cx={size/2} cy={size/2} r={r} fill="none"
          stroke={color} strokeWidth={8} strokeLinecap="round"
          strokeDasharray={`${dash} ${circ}`}
          style={{ transition: "stroke-dasharray 0.6s ease, stroke 0.4s" }}
        />
      </svg>
      <div style={{ position: "absolute", textAlign: "center" }}>
        <div style={{ fontSize: 20, fontWeight: 700, color, fontFamily: "monospace" }}>
          {(pct * 100).toFixed(1)}%
        </div>
      </div>
      {label && <div style={{ fontSize: 10, color: C.textDim, textTransform: "uppercase", letterSpacing: 1 }}>{label}</div>}
    </div>
  );
}

// ─── Agent Row ────────────────────────────────────────────────────────────────
function AgentRow({ agent, status, confidence, phaseColor }) {
  const st = status || "pending";
  const sc = STATUS_COLOR[st];
  const running = st === "running";

  return (
    <div style={{
      display: "grid", gridTemplateColumns: "28px 1fr auto auto",
      alignItems: "center", gap: 10,
      padding: "7px 12px",
      background: running ? "rgba(61,142,240,0.06)" : "transparent",
      borderLeft: `2px solid ${running ? C.blue : st === "done" ? phaseColor : C.border}`,
      transition: "all 0.3s",
      borderRadius: "0 4px 4px 0",
    }}>
      <div style={{ fontSize: 11, color: C.muted, fontFamily: "monospace" }}>
        {agent.num}
      </div>
      <div>
        <div style={{ fontSize: 12, color: running ? C.text : st === "done" ? C.text : C.textDim, fontWeight: 500 }}>
          {agent.label}
          {running && <span style={{ marginLeft: 6, color: C.blue, animation: "pulse 1s infinite" }}>●</span>}
        </div>
        <div style={{ fontSize: 10, color: C.muted, marginTop: 2 }}>{agent.desc}</div>
      </div>
      {st === "done" && (
        <div style={{ fontSize: 10, color: C.textDim, fontFamily: "monospace" }}>
          {(confidence * 100).toFixed(0)}%
        </div>
      )}
      <div style={{ fontSize: 13, color: sc, fontWeight: 700, minWidth: 16, textAlign: "center" }}>
        {STATUS_ICON[st]}
      </div>
    </div>
  );
}

// ─── Parameter display ────────────────────────────────────────────────────────
const SAMPLE_MODEL = {
  bridge_type: "double_cell_rcc_box",
  clear_span: 3375, clear_height: 1200,
  wall_thickness: 350, top_slab_thickness: 400,
  bottom_slab_thickness: 400, num_cells: 2,
  cell_widths: [3375, 3375], wing_wall_length: 3000,
  haunch_size: 150, road_width: 8500,
  waterway_area: 8.1, skew_angle: 0,
  levels: { RL: 100.850, HFL: 101.200, FL: 100.450, TOC: 101.650, BOF: 100.050 },
};

function ModelPanel({ visible }) {
  if (!visible) return null;
  const m = SAMPLE_MODEL;
  const rows = [
    ["Bridge Type", m.bridge_type.replace(/_/g," ").toUpperCase()],
    ["Clear Span (each cell)", `${m.clear_span} mm`],
    ["Clear Height", `${m.clear_height} mm`],
    ["Wall Thickness", `${m.wall_thickness} mm`],
    ["Top Slab", `${m.top_slab_thickness} mm`],
    ["Bottom Slab", `${m.bottom_slab_thickness} mm`],
    ["No. of Cells", m.num_cells],
    ["Haunch", `${m.haunch_size} mm`],
    ["Road Width", `${m.road_width} mm`],
    ["Waterway Area", `${m.waterway_area} m²`],
    ["RL", `${m.levels.RL} m`],
    ["HFL", `${m.levels.HFL} m`],
    ["FL", `${m.levels.FL} m`],
    ["TOC", `${m.levels.TOC} m`],
    ["BOF", `${m.levels.BOF} m`],
  ];

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 8, overflow: "hidden" }}>
      <div style={{ padding: "10px 14px", background: C.surface, borderBottom: `1px solid ${C.border}`, display:"flex", justifyContent:"space-between", alignItems:"center" }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: C.accent, letterSpacing: 1.5, textTransform:"uppercase" }}>Parametric Bridge Model</span>
        <span style={{ fontSize: 9, color: C.green, fontFamily:"monospace" }}>Agent 12 ✓</span>
      </div>
      <div style={{ padding: 8 }}>
        {rows.map(([k,v]) => (
          <div key={k} style={{ display:"grid", gridTemplateColumns:"1fr 1fr", padding:"4px 8px",
            borderBottom: `1px solid ${C.border}`, gap: 8 }}>
            <span style={{ fontSize: 11, color: C.textDim }}>{k}</span>
            <span style={{ fontSize: 11, color: C.text, fontFamily: "monospace", fontWeight: 600 }}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Mini Box Culvert SVG drawing ─────────────────────────────────────────────
function BoxCulvertSVG({ visible }) {
  if (!visible) return null;
  const W = 380, H = 220;
  const wt = 28, ts = 28, bs = 28, cw = 100, h_size = 10;
  const totalW = wt*3 + cw*2, totalH = ts + 120 + bs;
  const ox = (W - totalW) / 2, oy = (H - totalH) / 2;

  return (
    <div style={{ background: C.card, border:`1px solid ${C.border}`, borderRadius:8, overflow:"hidden" }}>
      <div style={{ padding:"10px 14px", background:C.surface, borderBottom:`1px solid ${C.border}`, display:"flex", justifyContent:"space-between", alignItems:"center" }}>
        <span style={{ fontSize:11, fontWeight:700, color:C.accent, letterSpacing:1.5, textTransform:"uppercase" }}>Generated Drawing Preview</span>
        <span style={{ fontSize:9, color:C.green, fontFamily:"monospace" }}>Agent 14 ✓</span>
      </div>
      <svg width={W} height={H} style={{ display:"block", background:C.bg }}>
        {/* Outer outline */}
        <rect x={ox} y={oy} width={totalW} height={totalH}
          fill="none" stroke={C.text} strokeWidth={1.5} />
        {/* Top slab */}
        <rect x={ox} y={oy} width={totalW} height={ts}
          fill="rgba(61,142,240,0.12)" stroke={C.blue} strokeWidth={1} />
        {/* Bottom slab */}
        <rect x={ox} y={oy+totalH-bs} width={totalW} height={bs}
          fill="rgba(61,142,240,0.12)" stroke={C.blue} strokeWidth={1} />
        {/* Left wall */}
        <rect x={ox} y={oy+ts} width={wt} height={totalH-ts-bs}
          fill="rgba(61,142,240,0.10)" stroke={C.blue} strokeWidth={1} />
        {/* Right wall */}
        <rect x={ox+totalW-wt} y={oy+ts} width={wt} height={totalH-ts-bs}
          fill="rgba(61,142,240,0.10)" stroke={C.blue} strokeWidth={1} />
        {/* Centre wall */}
        <rect x={ox+wt+cw} y={oy+ts} width={wt} height={totalH-ts-bs}
          fill="rgba(61,142,240,0.14)" stroke={C.blue} strokeWidth={1} />
        {/* Cell openings */}
        <rect x={ox+wt} y={oy+ts} width={cw} height={totalH-ts-bs}
          fill="rgba(0,0,0,0.3)" />
        <rect x={ox+wt*2+cw} y={oy+ts} width={cw} height={totalH-ts-bs}
          fill="rgba(0,0,0,0.3)" />
        {/* Haunches */}
        {[[ox+wt, oy+ts],[ox+wt*2+cw,oy+ts],[ox+wt,oy+totalH-bs],[ox+wt*2+cw,oy+totalH-bs],
          [ox+wt+cw,oy+ts],[ox+wt+cw+wt,oy+ts],[ox+wt+cw,oy+totalH-bs],[ox+wt+cw+wt,oy+totalH-bs]].map(([hx,hy],i)=>(
          <circle key={i} cx={hx} cy={hy} r={h_size} fill="rgba(245,166,35,0.2)" stroke={C.accent} strokeWidth={0.8} />
        ))}
        {/* Centreline */}
        <line x1={ox+totalW/2} y1={oy-12} x2={ox+totalW/2} y2={oy+totalH+12}
          stroke={C.red} strokeWidth={0.8} strokeDasharray="4 3" />
        {/* HFL */}
        <line x1={ox-8} y1={oy+ts+60} x2={ox+totalW+8} y2={oy+ts+60}
          stroke="#3d8ef0" strokeWidth={0.8} strokeDasharray="6 3" />
        <text x={ox+totalW+10} y={oy+ts+63} fill={C.blue} fontSize={7} fontFamily="monospace">HFL</text>
        {/* Dim lines */}
        {/* Cell 1 width dim */}
        <line x1={ox+wt} y1={oy+totalH+18} x2={ox+wt+cw} y2={oy+totalH+18} stroke={C.accent} strokeWidth={0.7} markerEnd="url(#arr)" />
        <text x={ox+wt+cw/2} y={oy+totalH+28} fill={C.accent} fontSize={7} textAnchor="middle" fontFamily="monospace">3375</text>
        {/* Cell 2 width dim */}
        <line x1={ox+wt*2+cw} y1={oy+totalH+18} x2={ox+wt*2+cw*2} y2={oy+totalH+18} stroke={C.accent} strokeWidth={0.7} />
        <text x={ox+wt*2+cw+cw/2} y={oy+totalH+28} fill={C.accent} fontSize={7} textAnchor="middle" fontFamily="monospace">3375</text>
        {/* Slab labels */}
        <text x={ox+totalW/2} y={oy+ts/2+3} fill={C.blue} fontSize={6.5} textAnchor="middle" fontFamily="monospace">TOP SLAB t=400</text>
        <text x={ox+totalW/2} y={oy+totalH-bs/2+3} fill={C.blue} fontSize={6.5} textAnchor="middle" fontFamily="monospace">BOT SLAB t=400</text>
        <text x={ox+wt/2} y={oy+totalH/2+3} fill={C.blue} fontSize={6} textAnchor="middle" fontFamily="monospace" transform={`rotate(-90,${ox+wt/2},${oy+totalH/2})`}>SIDE WALL</text>
        <text x={ox+wt*1.5+cw} y={oy+totalH/2+3} fill={C.blue} fontSize={6} textAnchor="middle" fontFamily="monospace" transform={`rotate(-90,${ox+wt*1.5+cw},${oy+totalH/2})`}>CTR WALL t=350</text>
        {/* Title */}
        <text x={W/2} y={H-6} fill={C.muted} fontSize={7.5} textAnchor="middle" fontFamily="monospace">
          DOUBLE CELL RCC BOX CULVERT — CROSS SECTION
        </text>
      </svg>
    </div>
  );
}

// ─── Architecture diagram ─────────────────────────────────────────────────────
function ArchDiagram() {
  const stacks = [
    { label:"ELECTRON DESKTOP", items:["React UI", "Agent Status Panel", "Drawing Viewer", "Export Controls"], color:"#3d8ef0" },
    { label:"FASTAPI BACKEND", items:["WebSocket API", "Session Manager", "LangGraph Pipeline", "File Handler"], color:"#a855f7" },
    { label:"AI AGENTS 1–16", items:["LangGraph Orchestration", "Claude API (LLM)", "PaddleOCR + Surya", "Detectron2 Vision"], color:C.accent },
    { label:"DATA LAYER", items:["PostgreSQL", "Neo4j Knowledge Graph", "ezdxf CAD Engine", "Shapely Geometry"], color:"#22c55e" },
  ];
  return (
    <div style={{ display:"grid", gridTemplateColumns:"repeat(4,1fr)", gap:8 }}>
      {stacks.map(s => (
        <div key={s.label} style={{ background:C.card, border:`1px solid ${s.color}33`, borderRadius:8, overflow:"hidden" }}>
          <div style={{ background:`${s.color}18`, padding:"8px 10px", borderBottom:`1px solid ${s.color}33` }}>
            <span style={{ fontSize:9, fontWeight:700, color:s.color, letterSpacing:1.2, textTransform:"uppercase" }}>{s.label}</span>
          </div>
          <div style={{ padding:"8px 10px" }}>
            {s.items.map(item => (
              <div key={item} style={{ fontSize:10.5, color:C.textDim, padding:"3px 0", borderBottom:`1px solid ${C.border}` }}>
                {item}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Main App ─────────────────────────────────────────────────────────────────
export default function RailBridgeAI() {
  const [tab, setTab] = useState("pipeline");
  const [running, setRunning] = useState(false);
  const [started, setStarted] = useState(false);
  const { statuses, confidences, overallConf, iteration, currentMsg, complete } =
    useSimulation(running);

  const doneCount = Object.values(statuses).filter(s => s === "done").length;
  const progress = doneCount / AGENTS.length;

  const handleStart = () => { setRunning(true); setStarted(true); };

  const TABS = [
    { id:"pipeline",   label:"PIPELINE" },
    { id:"model",      label:"DIGITAL TWIN" },
    { id:"drawing",    label:"CAD PREVIEW" },
    { id:"arch",       label:"ARCHITECTURE" },
  ];

  return (
    <div style={{
      minHeight: "100vh", background: C.bg, color: C.text,
      fontFamily: "'IBM Plex Mono', 'Courier New', monospace",
      display: "flex", flexDirection: "column",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&family=IBM+Plex+Sans:wght@400;600;700&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: ${C.bg}; }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
        @keyframes spin { to{transform:rotate(360deg)} }
        @keyframes fadeIn { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:none} }
        ::-webkit-scrollbar { width:5px; } ::-webkit-scrollbar-track { background:${C.bg}; }
        ::-webkit-scrollbar-thumb { background:${C.border}; border-radius:3px; }
      `}</style>

      {/* Header */}
      <div style={{
        background: C.surface, borderBottom: `1px solid ${C.border}`,
        padding: "0 24px", display: "flex", alignItems: "center", gap: 20,
        height: 54, flexShrink: 0,
      }}>
        {/* Logo */}
        <div style={{ display:"flex", alignItems:"center", gap: 10 }}>
          <svg width={28} height={28} viewBox="0 0 28 28">
            <rect width={28} height={28} rx={4} fill={C.accentDim} />
            <path d="M4 20 L14 6 L24 20" fill="none" stroke={C.accent} strokeWidth={2.5} />
            <rect x={10} y={15} width={8} height={5} fill={C.accent} />
            <line x1={4} y1={20} x2={24} y2={20} stroke={C.accent} strokeWidth={1.5} />
          </svg>
          <div>
            <div style={{ fontSize:13, fontWeight:700, color:C.accent, letterSpacing:1 }}>RAILBRIDGE<span style={{color:C.text}}>AI</span></div>
            <div style={{ fontSize:8, color:C.muted, letterSpacing:2, textTransform:"uppercase" }}>Multi-Agent Drawing Intelligence</div>
          </div>
        </div>

        {/* Tabs */}
        <div style={{ display:"flex", gap:2, marginLeft: 24 }}>
          {TABS.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)} style={{
              background: tab===t.id ? `${C.accent}18` : "transparent",
              border: `1px solid ${tab===t.id ? C.accent : "transparent"}`,
              color: tab===t.id ? C.accent : C.muted,
              padding:"5px 14px", borderRadius:4, cursor:"pointer",
              fontSize:10, fontWeight:700, letterSpacing:1.2,
              fontFamily:"inherit", transition:"all 0.2s",
            }}>{t.label}</button>
          ))}
        </div>

        <div style={{ marginLeft:"auto", display:"flex", alignItems:"center", gap:14 }}>
          {/* Overall confidence badge */}
          {overallConf > 0 && (
            <div style={{
              padding:"4px 12px", borderRadius:20,
              background: overallConf>=0.95 ? `${C.green}20` : `${C.accent}20`,
              border: `1px solid ${overallConf>=0.95 ? C.green : C.accent}`,
              fontSize:11, color: overallConf>=0.95 ? C.green : C.accent, fontWeight:700,
            }}>
              CONF {(overallConf*100).toFixed(1)}%
            </div>
          )}
          {complete && (
            <div style={{ padding:"4px 12px", borderRadius:20, background:`${C.green}20`,
              border:`1px solid ${C.green}`, fontSize:11, color:C.green, fontWeight:700 }}>
              ✓ APPROVED
            </div>
          )}
        </div>
      </div>

      {/* Main content */}
      <div style={{ flex:1, overflow:"hidden", display:"flex", flexDirection:"column" }}>

        {/* ─── PIPELINE TAB ── */}
        {tab === "pipeline" && (
          <div style={{ flex:1, overflow:"auto", padding:20, display:"grid", gridTemplateColumns:"1fr 340px", gap:16 }}>

            {/* Left: Agents */}
            <div style={{ display:"flex", flexDirection:"column", gap:12 }}>

              {/* Upload / Start */}
              {!started && (
                <div style={{ background:C.card, border:`2px dashed ${C.border}`, borderRadius:10,
                  padding:32, textAlign:"center", animation:"fadeIn 0.4s ease" }}>
                  <div style={{ fontSize:36, marginBottom:12 }}>📐</div>
                  <div style={{ fontSize:14, fontWeight:600, color:C.text, marginBottom:6 }}>
                    Drop scanned bridge drawing here
                  </div>
                  <div style={{ fontSize:11, color:C.muted, marginBottom:20 }}>
                    PDF · TIFF · PNG · JPG · Scanned GAD
                  </div>
                  <div style={{ display:"flex", gap:10, justifyContent:"center", flexWrap:"wrap" }}>
                    {["IRS Bridge Code", "IRBM", "RDSO"].map(s => (
                      <span key={s} style={{ fontSize:9, padding:"3px 10px", borderRadius:20,
                        background:`${C.accent}15`, border:`1px solid ${C.accentDim}`, color:C.accent }}>
                        {s}
                      </span>
                    ))}
                  </div>
                  <button onClick={handleStart} style={{
                    marginTop:24, padding:"10px 32px", background:C.accent, color:"#000",
                    border:"none", borderRadius:6, cursor:"pointer", fontSize:12,
                    fontWeight:700, fontFamily:"inherit", letterSpacing:1,
                  }}>
                    ▶ SIMULATE PROCESSING
                  </button>
                </div>
              )}

              {/* Progress bar */}
              {started && (
                <div style={{ background:C.card, border:`1px solid ${C.border}`, borderRadius:8, padding:14 }}>
                  <div style={{ display:"flex", justifyContent:"space-between", marginBottom:8, alignItems:"center" }}>
                    <span style={{ fontSize:10, color:C.muted, textTransform:"uppercase", letterSpacing:1 }}>
                      Pipeline Progress — Iteration {iteration+1}
                    </span>
                    <span style={{ fontSize:10, color:C.accent, fontFamily:"monospace" }}>
                      {doneCount}/{AGENTS.length} agents
                    </span>
                  </div>
                  <div style={{ height:6, background:C.border, borderRadius:3, overflow:"hidden" }}>
                    <div style={{
                      height:"100%", width:`${progress*100}%`, borderRadius:3,
                      background:`linear-gradient(90deg, ${C.blue}, ${C.accent}, ${C.green})`,
                      transition:"width 0.5s ease",
                    }} />
                  </div>
                  {currentMsg && (
                    <div style={{ marginTop:8, fontSize:10, color:C.blue, fontFamily:"monospace" }}>
                      ⟩ {currentMsg}
                    </div>
                  )}
                </div>
              )}

              {/* Phase groups */}
              {PHASES.map(phase => {
                const phaseAgents = AGENTS.filter(a => a.phase === phase.id);
                const phaseDone = phaseAgents.every(a => statuses[a.id] === "done");
                return (
                  <div key={phase.id} style={{
                    background:C.card, border:`1px solid ${phaseDone ? phase.color+"44" : C.border}`,
                    borderRadius:8, overflow:"hidden", transition:"border-color 0.4s"
                  }}>
                    <div style={{
                      padding:"8px 14px", background:`${phase.color}0d`,
                      borderBottom:`1px solid ${phaseDone ? phase.color+"44" : C.border}`,
                      display:"flex", justifyContent:"space-between", alignItems:"center"
                    }}>
                      <span style={{ fontSize:10, fontWeight:700, color:phase.color, letterSpacing:1.5 }}>
                        PHASE {phase.id} — {phase.label}
                      </span>
                      {phaseDone && started && (
                        <span style={{ fontSize:9, color:C.green }}>✓ COMPLETE</span>
                      )}
                    </div>
                    <div style={{ display:"flex", flexDirection:"column", gap:1, padding:"4px 0" }}>
                      {phaseAgents.map(agent => (
                        <AgentRow key={agent.id} agent={agent}
                          status={statuses[agent.id]} confidence={confidences[agent.id]}
                          phaseColor={phase.color} />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Right panel */}
            <div style={{ display:"flex", flexDirection:"column", gap:12 }}>

              {/* Confidence rings */}
              <div style={{ background:C.card, border:`1px solid ${C.border}`, borderRadius:8, padding:16 }}>
                <div style={{ fontSize:10, color:C.muted, letterSpacing:1.5, textTransform:"uppercase", marginBottom:16 }}>
                  System Confidence
                </div>
                <div style={{ display:"flex", justifyContent:"center", position:"relative", height:130 }}>
                  <ConfidenceRing value={overallConf} size={130} />
                  <div style={{ position:"absolute", top:"38%", left:"50%", transform:"translate(-50%,-50%)", textAlign:"center" }}>
                    <div style={{ fontSize:22, fontWeight:700, color: overallConf>=0.95?C.green:overallConf>0?C.accent:C.muted }}>
                      {overallConf > 0 ? `${(overallConf*100).toFixed(1)}%` : "—"}
                    </div>
                    <div style={{ fontSize:8, color:C.muted, marginTop:2 }}>OVERALL</div>
                  </div>
                </div>
                {/* Mini bars */}
                {[
                  {label:"Geometry", val: confidences["geometry_agent"]||0 },
                  {label:"Dimensions",val: confidences["dimension_agent"]||0 },
                  {label:"Levels",    val: confidences["level_agent"]||0 },
                  {label:"Standards", val: confidences["standards_agent"]||0 },
                  {label:"CAD Output",val: confidences["autocad_agent"]||0 },
                ].map(({label,val}) => (
                  <div key={label} style={{ marginTop:8 }}>
                    <div style={{ display:"flex", justifyContent:"space-between", marginBottom:3 }}>
                      <span style={{ fontSize:9, color:C.muted }}>{label}</span>
                      <span style={{ fontSize:9, color: val>=0.95?C.green:val>0?C.accent:C.muted, fontFamily:"monospace" }}>
                        {val > 0 ? `${(val*100).toFixed(0)}%` : "—"}
                      </span>
                    </div>
                    <div style={{ height:3, background:C.border, borderRadius:2 }}>
                      <div style={{ height:"100%", width:`${val*100}%`, borderRadius:2,
                        background: val>=0.95?C.green:C.accent, transition:"width 0.5s" }} />
                    </div>
                  </div>
                ))}
              </div>

              {/* Knowledge graph mini */}
              <div style={{ background:C.card, border:`1px solid ${C.border}`, borderRadius:8, padding:14 }}>
                <div style={{ fontSize:10, color:C.muted, letterSpacing:1.5, textTransform:"uppercase", marginBottom:12 }}>
                  Knowledge Graph
                </div>
                <svg width="100%" height={120} style={{ overflow:"visible" }}>
                  {/* Nodes */}
                  {[
                    {x:50,  y:30, label:"Bridge",     color:C.accent},
                    {x:150, y:20, label:"Span×2",     color:C.blue},
                    {x:240, y:30, label:"Wall",       color:"#a855f7"},
                    {x:50,  y:85, label:"Levels",     color:C.green},
                    {x:150, y:85, label:"Hydraulics", color:"#22d3ee"},
                    {x:240, y:85, label:"Standards",  color:C.red},
                  ].map(({x,y,label,color},i) => (
                    <g key={i}>
                      <circle cx={x} cy={y} r={18} fill={`${color}20`} stroke={color} strokeWidth={1.2}
                        opacity={started ? 1 : 0.3} style={{transition:"opacity 0.5s"}} />
                      <text x={x} y={y+4} textAnchor="middle" fontSize={7} fill={color} fontFamily="monospace">{label}</text>
                    </g>
                  ))}
                  {/* Edges */}
                  {[[50,30,150,20],[150,20,240,30],[50,30,50,85],[150,20,150,85],[240,30,240,85],[50,85,150,85],[150,85,240,85]].map(([x1,y1,x2,y2],i)=>(
                    <line key={i} x1={x1} y1={y1} x2={x2} y2={y2}
                      stroke={C.border} strokeWidth={1}
                      opacity={started ? 1 : 0.2} style={{transition:"opacity 0.5s"}} />
                  ))}
                </svg>
                <div style={{ fontSize:9, color:C.muted, marginTop:4 }}>
                  Neo4j — {started ? "12 nodes · 18 relationships" : "Awaiting processing"}
                </div>
              </div>

              {/* Output files */}
              {complete && (
                <div style={{ background:C.card, border:`1px solid ${C.green}44`, borderRadius:8, padding:14, animation:"fadeIn 0.4s ease" }}>
                  <div style={{ fontSize:10, color:C.green, letterSpacing:1.5, textTransform:"uppercase", marginBottom:10 }}>
                    ✓ Output Files Ready
                  </div>
                  {[
                    { icon:"📐", name:"bridge_drawing.dxf",   size:"2.4 MB", type:"DXF R2018" },
                    { icon:"📄", name:"bridge_drawing.scr",   size:"48 KB",  type:"AutoCAD Script" },
                    { icon:"📊", name:"extraction_report.pdf",size:"1.1 MB", type:"Report" },
                    { icon:"🔷", name:"parametric_model.json",size:"12 KB",  type:"Digital Twin" },
                  ].map(f => (
                    <div key={f.name} style={{ display:"flex", alignItems:"center", gap:10,
                      padding:"6px 0", borderBottom:`1px solid ${C.border}` }}>
                      <span style={{ fontSize:14 }}>{f.icon}</span>
                      <div style={{ flex:1 }}>
                        <div style={{ fontSize:10, color:C.text, fontFamily:"monospace" }}>{f.name}</div>
                        <div style={{ fontSize:8, color:C.muted }}>{f.type} · {f.size}</div>
                      </div>
                      <div style={{ fontSize:8, padding:"2px 8px", background:`${C.green}15`,
                        border:`1px solid ${C.green}44`, borderRadius:3, color:C.green }}>
                        READY
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ─── DIGITAL TWIN TAB ─── */}
        {tab === "model" && (
          <div style={{ flex:1, overflow:"auto", padding:20, display:"grid", gridTemplateColumns:"1fr 1fr", gap:16, alignContent:"start" }}>
            <ModelPanel visible={true} />
            <div style={{ display:"flex", flexDirection:"column", gap:12 }}>
              {/* Dimension chains */}
              <div style={{ background:C.card, border:`1px solid ${C.border}`, borderRadius:8, overflow:"hidden" }}>
                <div style={{ padding:"10px 14px", background:C.surface, borderBottom:`1px solid ${C.border}` }}>
                  <span style={{ fontSize:11, fontWeight:700, color:C.accent, letterSpacing:1.5, textTransform:"uppercase" }}>Dimension Chains (Agent 04)</span>
                </div>
                <div style={{ padding:12, display:"flex", flexDirection:"column", gap:8 }}>
                  {[
                    { label:"CELL WIDTHS (SECTION)", chain:[3375,350,3375], total:7100 },
                    { label:"WALL THICKNESSES",      chain:[350,350,350],  total:1050 },
                    { label:"SLAB HEIGHTS",          chain:[400,1200,400], total:2000 },
                    { label:"ROAD WIDTH",            chain:[1250,6000,1250],total:8500 },
                  ].map(({label,chain,total}) => (
                    <div key={label} style={{ background:C.bg, borderRadius:6, padding:10 }}>
                      <div style={{ fontSize:9, color:C.muted, letterSpacing:1, marginBottom:6 }}>{label}</div>
                      <div style={{ display:"flex", alignItems:"center", gap:4, flexWrap:"wrap" }}>
                        {chain.map((v,i) => (
                          <span key={i} style={{
                            padding:"2px 10px", borderRadius:3,
                            background: i===0||i===chain.length-1 ? `${C.blue}20` : `${C.accent}20`,
                            border: `1px solid ${i===0||i===chain.length-1 ? C.blue+"44" : C.accentDim}`,
                            color: i===0||i===chain.length-1 ? C.blue : C.accent,
                            fontSize:11, fontFamily:"monospace", fontWeight:600,
                          }}>{v}</span>
                        ))}
                        <span style={{ fontSize:10, color:C.muted, marginLeft:4 }}>= {total} mm</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Level table */}
              <div style={{ background:C.card, border:`1px solid ${C.border}`, borderRadius:8, overflow:"hidden" }}>
                <div style={{ padding:"10px 14px", background:C.surface, borderBottom:`1px solid ${C.border}` }}>
                  <span style={{ fontSize:11, fontWeight:700, color:C.accent, letterSpacing:1.5, textTransform:"uppercase" }}>Extracted Levels (Agent 06)</span>
                </div>
                <div style={{ padding:8 }}>
                  {[["RL", 100.850, true],["HFL",101.200,true],["FL",100.450,true],["TOC",101.650,true],["BOF",100.050,true],["CHFL",101.100,true]].map(([k,v,ok]) => (
                    <div key={k} style={{ display:"grid", gridTemplateColumns:"80px 1fr 30px",
                      alignItems:"center", padding:"5px 10px", borderBottom:`1px solid ${C.border}` }}>
                      <span style={{ fontSize:12, fontFamily:"monospace", fontWeight:700, color:C.accent }}>{k}</span>
                      <div style={{ display:"flex", alignItems:"center", gap:8 }}>
                        <span style={{ fontSize:12, fontFamily:"monospace", color:C.text }}>{v.toFixed(3)} m</span>
                        <div style={{ flex:1, height:3, background:C.border, borderRadius:2 }}>
                          <div style={{ height:"100%", width:`${((v-100)/2)*100}%`, background:C.blue, borderRadius:2 }} />
                        </div>
                      </div>
                      <span style={{ fontSize:11, color:C.green, textAlign:"right" }}>✓</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Validation summary */}
              <div style={{ background:C.card, border:`1px solid ${C.green}33`, borderRadius:8, overflow:"hidden" }}>
                <div style={{ padding:"10px 14px", background:`${C.green}0a`, borderBottom:`1px solid ${C.green}33` }}>
                  <span style={{ fontSize:11, fontWeight:700, color:C.green, letterSpacing:1.5, textTransform:"uppercase" }}>Standards Compliance (Agent 11)</span>
                </div>
                <div style={{ padding:10, display:"flex", flexDirection:"column", gap:6 }}>
                  {[
                    {code:"IRS CBC Cl.5.2",    item:"Min wall thickness 250mm",  result:"350mm ✓"},
                    {code:"RDSO-B-1",           item:"Clear height ≥1000mm",      result:"1200mm ✓"},
                    {code:"IRBM Para 8.3.4",    item:"Haunch size ≥150mm",        result:"150mm ✓"},
                    {code:"IRS CBC Cl.7.1",     item:"Top slab thickness ratio",  result:"OK ✓"},
                  ].map(({code,item,result}) => (
                    <div key={code} style={{ background:C.bg, borderRadius:5, padding:"7px 10px",
                      display:"grid", gridTemplateColumns:"90px 1fr auto", gap:8, alignItems:"center" }}>
                      <span style={{ fontSize:9, color:C.accent, fontFamily:"monospace" }}>{code}</span>
                      <span style={{ fontSize:10, color:C.textDim }}>{item}</span>
                      <span style={{ fontSize:10, color:C.green, fontFamily:"monospace" }}>{result}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ─── CAD PREVIEW TAB ─── */}
        {tab === "drawing" && (
          <div style={{ flex:1, overflow:"auto", padding:20, display:"grid", gridTemplateColumns:"1fr 1fr", gap:16, alignContent:"start" }}>
            <BoxCulvertSVG visible={true} />
            <div style={{ display:"flex", flexDirection:"column", gap:12 }}>
              {/* Layer table */}
              <div style={{ background:C.card, border:`1px solid ${C.border}`, borderRadius:8, overflow:"hidden" }}>
                <div style={{ padding:"10px 14px", background:C.surface, borderBottom:`1px solid ${C.border}` }}>
                  <span style={{ fontSize:11, fontWeight:700, color:C.accent, letterSpacing:1.5, textTransform:"uppercase" }}>AutoCAD Layer Table</span>
                </div>
                <div style={{ padding:8 }}>
                  {[
                    {name:"OUTLINE",      color:"WHITE",   lw:"0.50"},
                    {name:"DIMENSION",    color:"GREEN",   lw:"0.18"},
                    {name:"CENTERLINE",   color:"RED",     lw:"0.18"},
                    {name:"ANNOTATION",   color:"YELLOW",  lw:"0.18"},
                    {name:"LEVEL",        color:"CYAN",    lw:"0.18"},
                    {name:"WATERWAY",     color:"BLUE",    lw:"0.18"},
                    {name:"REINFORCEMENT",color:"MAGENTA", lw:"0.25"},
                    {name:"HATCH",        color:"8",       lw:"0.13"},
                  ].map(({name,color,lw}) => (
                    <div key={name} style={{ display:"grid", gridTemplateColumns:"1fr auto auto",
                      padding:"4px 10px", borderBottom:`1px solid ${C.border}`, alignItems:"center", gap:10 }}>
                      <span style={{ fontSize:11, fontFamily:"monospace", color:C.text }}>{name}</span>
                      <span style={{ fontSize:9, color:C.muted }}>{color}</span>
                      <span style={{ fontSize:9, fontFamily:"monospace", color:C.muted }}>{lw}mm</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Drawing stats */}
              <div style={{ background:C.card, border:`1px solid ${C.border}`, borderRadius:8, padding:14 }}>
                <div style={{ fontSize:10, color:C.muted, letterSpacing:1.5, textTransform:"uppercase", marginBottom:12 }}>Drawing Statistics</div>
                {[
                  {k:"DXF Version",      v:"AutoCAD R2018"},
                  {k:"Units",            v:"Millimetres"},
                  {k:"Total Entities",   v:"247"},
                  {k:"Lines",            v:"168"},
                  {k:"Polylines",        v:"24"},
                  {k:"Arcs (haunches)",  v:"16"},
                  {k:"Dimensions",       v:"31"},
                  {k:"Text entities",    v:"8"},
                  {k:"Geometry Similarity",v:"91.4%"},
                  {k:"Dim Similarity",   v:"96.2%"},
                  {k:"Annotation Sim",   v:"88.7%"},
                ].map(({k,v}) => (
                  <div key={k} style={{ display:"grid", gridTemplateColumns:"1fr auto", padding:"4px 0",
                    borderBottom:`1px solid ${C.border}` }}>
                    <span style={{ fontSize:11, color:C.muted }}>{k}</span>
                    <span style={{ fontSize:11, fontFamily:"monospace", color:C.text, fontWeight:600 }}>{v}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ─── ARCHITECTURE TAB ─── */}
        {tab === "arch" && (
          <div style={{ flex:1, overflow:"auto", padding:20, display:"flex", flexDirection:"column", gap:16 }}>
            <ArchDiagram />

            {/* LangGraph flow */}
            <div style={{ background:C.card, border:`1px solid ${C.border}`, borderRadius:8, overflow:"hidden" }}>
              <div style={{ padding:"10px 14px", background:C.surface, borderBottom:`1px solid ${C.border}` }}>
                <span style={{ fontSize:11, fontWeight:700, color:C.accent, letterSpacing:1.5, textTransform:"uppercase" }}>LangGraph Pipeline Flow</span>
              </div>
              <div style={{ padding:16, overflowX:"auto" }}>
                <svg width={820} height={80} style={{ minWidth:820 }}>
                  {AGENTS.map((a,i) => {
                    const x = i * 50 + 20;
                    const phase = PHASES.find(p=>p.id===a.phase);
                    return (
                      <g key={a.id}>
                        <circle cx={x} cy={35} r={14} fill={`${phase.color}20`} stroke={phase.color} strokeWidth={1.2} />
                        <text x={x} y={39} textAnchor="middle" fontSize={7} fill={phase.color} fontFamily="monospace">{a.num}</text>
                        <text x={x} y={62} textAnchor="middle" fontSize={6.5} fill={C.muted} fontFamily="monospace"
                          style={{writingMode:"horizontal-tb"}}>{a.label.split(" ")[0]}</text>
                        {i < AGENTS.length-1 && (
                          <line x1={x+14} y1={35} x2={x+36} y2={35} stroke={C.border} strokeWidth={1} markerEnd="url(#arr2)" />
                        )}
                        {/* Challenger loop back arrow */}
                        {a.id === "challenger_agent" && (
                          <path d={`M ${x} 20 Q ${x-100} -10 ${x-200} 20`}
                            fill="none" stroke={C.yellow} strokeWidth={0.8} strokeDasharray="4 3" />
                        )}
                        {/* Final QA loop back */}
                        {a.id === "final_qa_agent" && (
                          <path d={`M ${x} 20 Q ${x-150} -15 ${x-300} 20`}
                            fill="none" stroke={C.green} strokeWidth={0.8} strokeDasharray="4 3" />
                        )}
                      </g>
                    );
                  })}
                  <defs>
                    <marker id="arr2" markerWidth="5" markerHeight="5" refX="5" refY="2.5" orient="auto">
                      <path d="M0,0 L5,2.5 L0,5" fill={C.border} />
                    </marker>
                  </defs>
                </svg>
                <div style={{ display:"flex", gap:16, marginTop:12 }}>
                  {PHASES.map(p => (
                    <div key={p.id} style={{ display:"flex", alignItems:"center", gap:6 }}>
                      <div style={{ width:10, height:10, borderRadius:"50%", background:p.color }} />
                      <span style={{ fontSize:9, color:C.muted }}>{p.label}</span>
                    </div>
                  ))}
                  <div style={{ display:"flex", alignItems:"center", gap:6 }}>
                    <div style={{ width:20, height:2, background:C.yellow, borderRadius:1 }} />
                    <span style={{ fontSize:9, color:C.muted }}>Challenger loop</span>
                  </div>
                  <div style={{ display:"flex", alignItems:"center", gap:6 }}>
                    <div style={{ width:20, height:2, background:C.green, borderRadius:1 }} />
                    <span style={{ fontSize:9, color:C.muted }}>QA iterate loop</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Tech stack chips */}
            <div style={{ background:C.card, border:`1px solid ${C.border}`, borderRadius:8, padding:14 }}>
              <div style={{ fontSize:10, color:C.muted, letterSpacing:1.5, textTransform:"uppercase", marginBottom:12 }}>Technology Stack</div>
              <div style={{ display:"flex", flexWrap:"wrap", gap:8 }}>
                {[
                  {l:"Electron",          c:C.blue},   {l:"React",          c:C.blue},
                  {l:"Python 3.12",       c:"#f7c948"},{l:"FastAPI",        c:"#059669"},
                  {l:"LangGraph",         c:C.accent}, {l:"Claude API",     c:C.accent},
                  {l:"PaddleOCR",         c:"#a855f7"},{l:"Surya OCR",      c:"#a855f7"},
                  {l:"OpenCV",            c:"#22d3ee"},{l:"Detectron2",     c:"#22d3ee"},
                  {l:"Shapely",           c:C.green},  {l:"NetworkX",       c:C.green},
                  {l:"ezdxf",             c:C.red},    {l:"Autodesk API",   c:C.red},
                  {l:"PostgreSQL",        c:"#3b82f6"},{l:"Neo4j",          c:"#10b981"},
                  {l:"Docker",            c:"#0ea5e9"},{l:"IRS Bridge Code",c:C.muted},
                ].map(({l,c}) => (
                  <span key={l} style={{ fontSize:10, padding:"3px 10px", borderRadius:4,
                    background:`${c}15`, border:`1px solid ${c}44`, color:c, fontFamily:"monospace" }}>
                    {l}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div style={{ background:C.surface, borderTop:`1px solid ${C.border}`, padding:"6px 20px",
        display:"flex", justifyContent:"space-between", alignItems:"center", flexShrink:0 }}>
        <span style={{ fontSize:9, color:C.muted }}>RAILBRIDGEAI v1.0 · 16-Agent Pipeline · Indian Railways Bridge Engineering</span>
        <span style={{ fontSize:9, color:C.muted, fontFamily:"monospace" }}>
          {doneCount > 0 ? `${doneCount}/16 AGENTS · ITER ${iteration+1}` : "READY"}
        </span>
      </div>
    </div>
  );
}
