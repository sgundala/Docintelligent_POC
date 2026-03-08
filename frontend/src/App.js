import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import {
  Upload, FileText, CheckCircle, AlertCircle, Clock, ChevronRight,
  Download, RefreshCw, Eye, Edit3, X, Check, Sparkles, Activity,
  Database, Shield, BarChart2, List, Layers
} from 'lucide-react';
import './App.css';

const API = process.env.REACT_APP_API_URL || '';

// ── helpers ───────────────────────────────────────────────────────────────────
const api = axios.create({ baseURL: API });

function pct(v) { return Math.round(v); }

function confColor(c) {
  if (c >= 0.9) return 'var(--green)';
  if (c >= 0.7) return 'var(--amber)';
  return 'var(--red)';
}

function sourceLabel(s) {
  const m = {
    groq_llm:'Groq LLM', groq_llm_section:'Groq Section', groq_rag:'Groq RAG',
    heuristic_regex:'Regex', heuristic_section:'Section Regex', heuristic_rag:'RAG Regex',
    sample_data:'Sample', groq_suggestion:'Groq', heuristic_default:'Default', suggestion_accept:'Accepted', suggestion_edit:'Edited'
  };
  return m[s] || s;
}

function docTypeLabel(t) {
  const m = { clinical_evaluation_protocol:'Clinical Evaluation Protocol', risk_management_report:'Risk Management Report', test_protocol:'Test Protocol', design_history_file:'Design History File', unknown:'Unknown' };
  return m[t] || t;
}

const FIELD_LABELS = {
  document_title:'Document Title', document_number:'Document Number', version:'Version',
  date:'Date', device_name:'Device Name', device_model:'Device Model',
  intended_purpose:'Intended Purpose', manufacturer_name:'Manufacturer',
  regulatory_framework:'Regulatory Framework', evaluation_scope:'Evaluation Scope',
  literature_search_strategy:'Literature Search Strategy', inclusion_criteria:'Inclusion Criteria',
  exclusion_criteria:'Exclusion Criteria', clinical_data_sources:'Clinical Data Sources',
  equivalence_device:'Equivalence Device', benefit_risk_assessment:'Benefit-Risk Assessment',
  conclusions:'Conclusions', author:'Author', reviewer:'Reviewer',
  device_classification:'Device Classification', predicate_device:'Predicate Device',
  post_market_surveillance_ref:'PMS Reference', notified_body:'Notified Body',
  approval_date:'Approval Date',
  biocompatibility_standard:'Biocompatibility Standard',
  biological_endpoints_evaluated:'Biological Endpoints Evaluated',
  biocompatibility_assessment:'Biocompatibility Assessment',
  cytotoxicity_result:'Cytotoxicity Result',
  sensitization_result:'Sensitization Result',
  irritation_result:'Irritation Result',
};

// ── Ring chart ─────────────────────────────────────────────────────────────────
function RingChart({ value, size = 80, stroke = 8, color = 'var(--accent)' }) {
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ - (value / 100) * circ;
  return (
    <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="var(--border2)" strokeWidth={stroke} />
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color}
        strokeWidth={stroke} strokeDasharray={circ} strokeDashoffset={offset}
        strokeLinecap="round" style={{ transition: 'stroke-dashoffset .6s ease' }} />
      <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central"
        fill="var(--text)" fontSize={size * 0.22} fontFamily="var(--mono)"
        style={{ transform: 'rotate(90deg)', transformOrigin: 'center' }}>
        {pct(value)}%
      </text>
    </svg>
  );
}

// ── Progress bar ───────────────────────────────────────────────────────────────
function ProgressBar({ value, color = 'var(--accent)', height = 6 }) {
  return (
    <div style={{ background: 'var(--border)', borderRadius: 999, height, overflow: 'hidden' }}>
      <div style={{
        width: `${value}%`, height: '100%', background: color,
        borderRadius: 999, transition: 'width .5s ease'
      }} />
    </div>
  );
}

// ── Badge ─────────────────────────────────────────────────────────────────────
function Badge({ children, color = 'var(--accent)', bg }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px',
      borderRadius: 4, fontSize: 11, fontFamily: 'var(--mono)', fontWeight: 500,
      color, background: bg || `${color}18`, border: `1px solid ${color}30`
    }}>{children}</span>
  );
}

// ── UploadZone ─────────────────────────────────────────────────────────────────
function UploadZone({ onUploaded, loading, setLoading }) {
  const [drag, setDrag] = useState(false);

  const handleFiles = useCallback(async (files) => {
    if (!files.length) return;
    setLoading(true);
    for (const file of files) {
      const fd = new FormData();
      fd.append('file', file);
      try {
        await api.post('/api/documents/upload', fd);
      } catch (e) {
        console.error(e);
      }
    }
    setLoading(false);
    onUploaded();
  }, [onUploaded, setLoading]);

  return (
    <div className={`upload-zone ${drag ? 'drag' : ''}`}
      onDragOver={e => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={e => { e.preventDefault(); setDrag(false); handleFiles([...e.dataTransfer.files]); }}>
      <Upload size={28} strokeWidth={1.5} color="var(--muted)" />
      <span style={{ color: 'var(--muted)', marginTop: 8 }}>Drop PDF, DOCX, or TXT files here</span>
      <label className="btn-secondary" style={{ marginTop: 12 }}>
        {loading ? <><RefreshCw size={14} className="spin" /> Processing…</> : 'Browse files'}
        <input type="file" multiple accept=".pdf,.docx,.txt" style={{ display:'none' }}
          onChange={e => handleFiles([...e.target.files])} />
      </label>
    </div>
  );
}

// ── DocCard ────────────────────────────────────────────────────────────────────
function DocCard({ doc, selected, onClick }) {
  const c = doc.completeness;
  const color = c.completeness_pct >= 80 ? 'var(--green)' : c.completeness_pct >= 50 ? 'var(--amber)' : 'var(--red)';
  return (
    <div className={`doc-card ${selected ? 'selected' : ''}`} onClick={onClick}>
      <div style={{ display:'flex', alignItems:'flex-start', gap:12 }}>
        <FileText size={18} color="var(--accent)" strokeWidth={1.5} style={{ marginTop:2, flexShrink:0 }} />
        <div style={{ flex:1, minWidth:0 }}>
          <div style={{ fontWeight:500, fontSize:13, color:'var(--text)', whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>
            {doc.filename}
          </div>
          <div style={{ fontSize:11, color:'var(--muted)', marginTop:2 }}>
            {docTypeLabel(doc.doc_type)}
          </div>
        </div>
        <RingChart value={c.completeness_pct} size={48} stroke={5} color={color} />
      </div>
      <div style={{ marginTop:10 }}>
        <ProgressBar value={c.completeness_pct} color={color} />
        <div style={{ display:'flex', justifyContent:'space-between', marginTop:4, fontSize:11, color:'var(--muted)' }}>
          <span>{c.required_present}/{c.required_total} required fields</span>
          {doc.suggestions?.filter(s=>s.status==='pending').length > 0 &&
            <Badge color="var(--amber)">{doc.suggestions.filter(s=>s.status==='pending').length} suggestions</Badge>}
        </div>
      </div>
    </div>
  );
}

// ── FieldRow ───────────────────────────────────────────────────────────────────
function FieldRow({ elem, onEdit }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(elem.value);
  const [showEvidence, setShowEvidence] = useState(false);

  const save = async () => {
    await onEdit(elem.elem_id, val);
    setEditing(false);
  };

  return (
    <div className="field-row">
      <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:4 }}>
        <span style={{ fontSize:12, fontWeight:600, color:'var(--muted)', textTransform:'uppercase', letterSpacing:.5, minWidth:180 }}>
          {FIELD_LABELS[elem.field] || elem.field}
        </span>
        <Badge color={confColor(elem.confidence)}>{Math.round(elem.confidence*100)}%</Badge>
        <Badge color="var(--purple)">{sourceLabel(elem.source)}</Badge>
        {elem.section && <Badge color="var(--accent)">{elem.section}</Badge>}
        {elem.edited && <Badge color="var(--cyan)">Edited</Badge>}
      </div>
      {editing ? (
        <div style={{ display:'flex', gap:8, alignItems:'flex-start' }}>
          <textarea className="field-input" value={val}
            onChange={e => setVal(e.target.value)} rows={2} style={{ flex:1 }} />
          <button className="btn-icon green" onClick={save}><Check size={14}/></button>
          <button className="btn-icon red" onClick={() => { setVal(elem.value); setEditing(false); }}><X size={14}/></button>
        </div>
      ) : (
        <div style={{ display:'flex', gap:8, alignItems:'flex-start' }}>
          <div style={{ flex:1, fontSize:13, color:'var(--text)', lineHeight:1.5, wordBreak:'break-word' }}>{elem.value || <em style={{color:'var(--muted)'}}>—</em>}</div>
          <button className="btn-icon" onClick={() => setEditing(true)} title="Edit"><Edit3 size={13}/></button>
          {elem.evidence && <button className="btn-icon" onClick={() => setShowEvidence(!showEvidence)} title="Evidence"><Eye size={13}/></button>}
        </div>
      )}
      {showEvidence && elem.evidence && (
        <div className="evidence-box">
          <span style={{ color:'var(--muted)', fontSize:11, fontFamily:'var(--mono)' }}>Evidence: </span>
          <span style={{ fontSize:12, color:'var(--cyan)', fontFamily:'var(--mono)' }}>…{elem.evidence}…</span>
        </div>
      )}
    </div>
  );
}

// ── SuggestionCard ─────────────────────────────────────────────────────────────
function SuggestionCard({ sugg, onAction }) {
  const [editMode, setEditMode] = useState(false);
  const [val, setVal] = useState(sugg.suggested_value);
  const resolved = sugg.status && sugg.status !== 'pending';
  const statusColor = sugg.status === 'reject' ? 'var(--red)' : sugg.status === 'edit' ? 'var(--cyan)' : 'var(--green)';
  const statusLabel = sugg.status === 'reject' ? 'Rejected' : sugg.status === 'edit' ? 'Edited' : sugg.status === 'accept' ? 'Accepted' : sugg.status;
  return (
    <div className="suggestion-card">
      <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:6 }}>
        <Sparkles size={14} color="var(--amber)" />
        <span style={{ fontWeight:600, fontSize:12, color:'var(--text)', textTransform:'uppercase', letterSpacing:.5 }}>
          {FIELD_LABELS[sugg.field] || sugg.field}
        </span>
        <Badge color="var(--amber)">{sourceLabel(sugg.source)}</Badge>
        {resolved && <Badge color={statusColor}>{statusLabel}</Badge>}
      </div>
      {editMode ? (
        <textarea className="field-input" value={val} onChange={e=>setVal(e.target.value)} rows={2} style={{width:'100%',marginBottom:8}} />
      ) : (
        <div style={{ fontSize:13, color:'var(--text)', marginBottom:6, lineHeight:1.5 }}>{val}</div>
      )}
      <div style={{ fontSize:11, color:'var(--muted)', marginBottom:10, fontStyle:'italic' }}>
        {sugg.rationale}
      </div>
      <div style={{ display:'flex', gap:8 }}>
        {resolved ? (
          <button className="btn-sm muted" disabled><Check size={12}/> Actioned</button>
        ) : (
          (editMode ? (
            <>
              <button className="btn-sm green" onClick={() => { onAction(sugg.id,'edit',val); setEditMode(false); }}>
                <Check size={12}/> Save & Accept
              </button>
              <button className="btn-sm muted" onClick={() => setEditMode(false)}><X size={12}/> Cancel</button>
            </>
          ) : (
            <>
              <button className="btn-sm green" onClick={() => onAction(sugg.id,'accept')}><Check size={12}/> Accept</button>
              <button className="btn-sm amber" onClick={() => setEditMode(true)}><Edit3 size={12}/> Edit</button>
              <button className="btn-sm red" onClick={() => onAction(sugg.id,'reject')}><X size={12}/> Reject</button>
            </>
          ))
        )}
      </div>
    </div>
  );
}

// ── DocDetail ──────────────────────────────────────────────────────────────────
function DocDetail({ docId, onUpdate }) {
  const [doc, setDoc] = useState(null);
  const [schemaInfo, setSchemaInfo] = useState(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generatingDocx, setGeneratingDocx] = useState(false);
  const [tab, setTab] = useState('fields'); // fields | sections | suggestions | missing | templates | trace

  const load = useCallback(async () => {
    if (!docId) return;
    const [docResp, schemaResp] = await Promise.all([
      api.get(`/api/documents/${docId}`),
      api.get('/api/schema')
    ]);
    setDoc(docResp.data);
    setSchemaInfo(schemaResp.data);
  }, [docId]);

  useEffect(() => { load(); }, [load]);

  const editField = async (elem_id, new_value) => {
    await api.patch(`/api/documents/${docId}/fields`, { elem_id, new_value });
    await load(); onUpdate();
  };

  const actSuggestion = async (sugg_id, action, edited_value) => {
    await api.post(`/api/documents/${docId}/suggestions/${sugg_id}`, { action, edited_value });
    await load(); onUpdate();
  };

  const generate = async () => {
    setGenerating(true);
    await api.post(`/api/documents/${docId}/generate`);
    await load(); onUpdate();
    setGenerating(false);
  };

  const generateDocx = async () => {
    setGeneratingDocx(true);
    await api.post(`/api/documents/${docId}/generate-docx`);
    await load(); onUpdate();
    setGeneratingDocx(false);
  };

  if (!doc) return <div className="empty-state"><RefreshCw size={20} className="spin" /></div>;

  const c = doc.completeness;
  const color = c.completeness_pct >= 80 ? 'var(--green)' : c.completeness_pct >= 50 ? 'var(--amber)' : 'var(--red)';
  const pendingSuggs = doc.suggestions?.filter(s => s.status==='pending') || [];
  const resolvedSuggs = doc.suggestions?.filter(s => s.status && s.status !== 'pending') || [];
  const allFields = doc.elements || [];
  const elemByField = {};
  allFields.forEach(e => { elemByField[e.field] = e; });
  const effectiveSchema = schemaInfo?.effective_doc_schemas?.[doc.doc_type] || null;
  const templateFields = effectiveSchema?.template_fields || [];
  const presentTemplateFields = templateFields.filter(f => Boolean(elemByField[f]?.value?.toString().trim()));
  const missingTemplateFields = templateFields.filter(f => !presentTemplateFields.includes(f));
  const templateCoverage = templateFields.length ? Math.round((presentTemplateFields.length / templateFields.length) * 100) : 0;
  const sectionSummary = doc.section_summary || [];

  return (
    <div className="doc-detail">
      {/* Header */}
      <div className="detail-header">
        <div>
          <div style={{ fontSize:16, fontWeight:600 }}>{doc.filename}</div>
          <div style={{ fontSize:12, color:'var(--muted)', marginTop:2 }}>
            {docTypeLabel(doc.doc_type)} · {new Date(doc.uploaded_at).toLocaleString()}
          </div>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:12 }}>
          {doc.status === 'output_generated' && (
            <a className="btn-secondary" href={`${API}/api/documents/${docId}/download`} target="_blank" rel="noreferrer">
              <Download size={14} /> Download
            </a>
          )}
          <a className="btn-secondary" href={`${API}/api/documents/${docId}/download-docx`} target="_blank" rel="noreferrer">
            <Download size={14} /> Download DOCX
          </a>
          <button className="btn-secondary" onClick={generateDocx} disabled={generatingDocx}>
            {generatingDocx ? <><RefreshCw size={14} className="spin" /> DOCX…</> : <><FileText size={14}/> Generate DOCX</>}
          </button>
          <button className="btn-primary" onClick={generate} disabled={generating}>
            {generating ? <><RefreshCw size={14} className="spin" /> Generating…</> : <><FileText size={14}/> Generate Output</>}
          </button>
        </div>
      </div>

      {/* Completeness strip */}
      <div className="completeness-strip">
        <RingChart value={c.completeness_pct} size={72} stroke={7} color={color} />
        <div style={{ flex:1 }}>
          <div style={{ display:'flex', justifyContent:'space-between', marginBottom:6 }}>
            <span style={{ fontWeight:600 }}>Completeness</span>
            <span style={{ color:'var(--muted)', fontSize:12 }}>{c.required_present}/{c.required_total} required · {c.optional_present}/{c.optional_total} optional</span>
          </div>
          <ProgressBar value={c.completeness_pct} color={color} height={8} />
          {c.missing_required.length > 0 && (
            <div style={{ marginTop:8, display:'flex', flexWrap:'wrap', gap:4 }}>
              {c.missing_required.map(f => (
                <Badge key={f} color="var(--red)">{FIELD_LABELS[f]||f}</Badge>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="tabs">
        {[
          { id:'fields', label:'Fields', icon:<List size={14}/>, count: allFields.length },
          { id:'sections', label:'Sections', icon:<BarChart2 size={14}/>, count: sectionSummary.length },
          { id:'suggestions', label:'Suggestions', icon:<Sparkles size={14}/>, count: pendingSuggs.length },
          { id:'missing', label:'Missing', icon:<AlertCircle size={14}/>, count: c.missing_required.length },
          { id:'templates', label:'Templates', icon:<Database size={14}/>, count: templateFields.length },
          { id:'trace', label:'Traceability', icon:<Shield size={14}/> },
        ].map(t => (
          <button key={t.id} className={`tab ${tab===t.id?'active':''}`} onClick={() => setTab(t.id)}>
            {t.icon} {t.label}
            {t.count > 0 && <span className="tab-badge">{t.count}</span>}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="tab-content">
        {tab === 'fields' && (
          <div>
            {allFields.length === 0 && <div className="empty-state">No fields extracted yet.</div>}
            {allFields.map(e => <FieldRow key={e.elem_id} elem={e} onEdit={editField} />)}
          </div>
        )}

        {tab === 'sections' && (
          <div>
            {sectionSummary.length === 0 && (
              <div className="empty-state">
                <BarChart2 size={24} color="var(--muted)" />
                <span>No section map available for this document.</span>
              </div>
            )}
            {sectionSummary.map(sec => (
              <div key={sec.heading} className="trace-block">
                <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                  <div className="trace-label" style={{ marginBottom: 0 }}>{sec.heading}</div>
                  <Badge color={sec.completeness_pct >= 70 ? 'var(--green)' : sec.completeness_pct >= 40 ? 'var(--amber)' : 'var(--red)'}>
                    {Math.round(sec.completeness_pct)}%
                  </Badge>
                </div>
                <div style={{ marginTop: 8 }}>
                  <ProgressBar value={sec.completeness_pct || 0} color={sec.completeness_pct >= 70 ? 'var(--green)' : 'var(--amber)'} />
                </div>
                <div style={{ marginTop: 8, display:'flex', gap:8, flexWrap:'wrap' }}>
                  <Badge color="var(--green)">{sec.required_present || 0} required present</Badge>
                  <Badge color="var(--red)">{Math.max((sec.required_total || 0) - (sec.required_present || 0), 0)} required missing</Badge>
                  <Badge color="var(--accent)">{sec.section_key || 'other'}</Badge>
                </div>
                <div style={{ marginTop: 8 }}>
                  <div style={{ fontSize:11, color:'var(--muted)', textTransform:'uppercase', letterSpacing:.5, marginBottom:6 }}>
                    Extracted Here
                  </div>
                  <div style={{ display:'flex', gap:4, flexWrap:'wrap' }}>
                    {(sec.fields_present || []).length === 0 && <Badge color="var(--muted)">None</Badge>}
                    {(sec.fields_present || []).map(f => (
                      <Badge key={`${sec.heading}-field-${f}`} color="var(--cyan)">{FIELD_LABELS[f] || f}</Badge>
                    ))}
                  </div>
                </div>
                {(sec.misaligned_required_fields || []).length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <div style={{ fontSize:11, color:'var(--muted)', textTransform:'uppercase', letterSpacing:.5, marginBottom:6 }}>
                      Required But In Different Section Pattern
                    </div>
                    <div style={{ display:'flex', gap:4, flexWrap:'wrap' }}>
                      {(sec.misaligned_required_fields || []).map(f => (
                        <Badge key={`${sec.heading}-mis-${f}`} color="var(--amber)">{FIELD_LABELS[f] || f}</Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {tab === 'suggestions' && (
          <div>
            {pendingSuggs.length === 0 && (
              <div className="empty-state">
                <CheckCircle size={24} color="var(--green)" />
                <span>All suggestions resolved.</span>
              </div>
            )}
            {pendingSuggs.map(s => (
              <SuggestionCard key={s.id} sugg={s} onAction={actSuggestion} />
            ))}
            {resolvedSuggs.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <div style={{ fontSize:11, color:'var(--muted)', textTransform:'uppercase', letterSpacing:.5, marginBottom:8 }}>
                  Resolved Suggestions
                </div>
                {resolvedSuggs.map(s => (
                  <SuggestionCard key={s.id} sugg={s} onAction={actSuggestion} />
                ))}
              </div>
            )}
          </div>
        )}

        {tab === 'missing' && (
          <div>
            {c.missing_required.length === 0 && (
              <div className="empty-state"><CheckCircle size={24} color="var(--green)" /><span>No missing required fields!</span></div>
            )}
            {c.missing_required.map(f => (
              <div key={f} className="missing-row">
                <AlertCircle size={14} color="var(--red)" style={{ flexShrink:0 }} />
                <span style={{ fontWeight:500, color:'var(--text)' }}>{FIELD_LABELS[f]||f}</span>
                <span style={{ fontSize:11, color:'var(--muted)', marginLeft:'auto' }}>Required — not found</span>
              </div>
            ))}
          </div>
        )}

        {tab === 'templates' && (
          <div>
            {templateFields.length === 0 && (
              <div className="empty-state">
                <Database size={24} color="var(--muted)" />
                <span>No template-derived fields for this document type yet.</span>
              </div>
            )}
            {templateFields.length > 0 && (
              <>
                <div className="trace-block">
                  <div className="trace-label">Template Coverage</div>
                  <div style={{ marginTop: 8 }}>
                    <ProgressBar value={templateCoverage} color={templateCoverage >= 70 ? 'var(--green)' : 'var(--amber)'} height={8} />
                    <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
                      <Badge color="var(--green)">{presentTemplateFields.length} present</Badge>
                      <Badge color="var(--red)">{missingTemplateFields.length} missing</Badge>
                      <Badge color="var(--accent)">{templateCoverage}%</Badge>
                    </div>
                  </div>
                </div>
                <div className="trace-block">
                  <div className="trace-label">Missing Template Fields</div>
                  <div style={{ marginTop: 8, display:'flex', flexWrap:'wrap', gap:4 }}>
                    {missingTemplateFields.length === 0 && <Badge color="var(--green)">All template fields covered</Badge>}
                    {missingTemplateFields.map(f => (
                      <Badge key={f} color="var(--red)">{FIELD_LABELS[f] || f}</Badge>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {tab === 'trace' && (
          <div>
            <div className="trace-block">
              <div className="trace-label">Document SHA-256</div>
              <div className="trace-value mono">{doc.sha256}</div>
            </div>
            <div className="trace-block">
              <div className="trace-label">Ingested At</div>
              <div className="trace-value">{doc.uploaded_at}</div>
            </div>
            <div className="trace-block">
              <div className="trace-label">Status</div>
              <div className="trace-value"><Badge color="var(--accent)">{doc.status}</Badge></div>
            </div>
            <div className="trace-block">
              <div className="trace-label">Field Provenance</div>
              <div style={{ marginTop:8 }}>
                {allFields.map(e => (
                  <div key={e.elem_id} className="provenance-row">
                    <span style={{ color:'var(--muted)', fontFamily:'var(--mono)', fontSize:11, minWidth:200 }}>{e.field}</span>
                    <Badge color="var(--purple)">{sourceLabel(e.source)}</Badge>
                    <span style={{ color:'var(--muted)', fontSize:11 }}>{Math.round(e.confidence*100)}% conf</span>
                    {e.edited && <Badge color="var(--cyan)">Edited {e.edited_at?.slice(0,10)}</Badge>}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── PackageSummary ─────────────────────────────────────────────────────────────
function PackageSummary({ docs, pkgPct, packageData }) {
  const color = pkgPct >= 80 ? 'var(--green)' : pkgPct >= 50 ? 'var(--amber)' : 'var(--red)';
  const matrix = packageData?.output_template_matrix || [];
  const [incompleteOnly, setIncompleteOnly] = useState(false);
  const shown = incompleteOnly ? matrix.filter(m => (m.completeness_pct || 0) < 100) : matrix;
  return (
    <div className="pkg-summary">
      <div style={{ display:'flex', alignItems:'center', gap:12 }}>
        <Layers size={16} color="var(--accent)" />
        <span style={{ fontWeight:600, fontSize:13 }}>Package Completeness</span>
        <span style={{ fontSize:12, color:'var(--muted)', marginLeft:'auto' }}>{docs.length} document{docs.length!==1?'s':''}</span>
      </div>
      <div style={{ display:'flex', alignItems:'center', gap:16, marginTop:10 }}>
        <ProgressBar value={pkgPct} color={color} height={10} />
        <span style={{ fontFamily:'var(--mono)', fontSize:16, fontWeight:600, color, minWidth:50, textAlign:'right' }}>{pkgPct}%</span>
      </div>
      {matrix.length > 0 && (
        <div style={{ marginTop: 10, display:'grid', gap:6 }}>
          <label style={{ display:'flex', alignItems:'center', gap:6, fontSize:11, color:'var(--muted)' }}>
            <input type="checkbox" checked={incompleteOnly} onChange={e => setIncompleteOnly(e.target.checked)} />
            Show only incomplete rows
          </label>
          {shown.slice(0, 8).map((m, i) => (
            <div key={`${m.template_id || m.filename}-${i}`} style={{ border:'1px solid var(--border)', borderRadius:6, padding:'6px 8px' }}>
              <div style={{ display:'flex', justifyContent:'space-between', gap:8 }}>
                <span style={{ fontSize:11, color:'var(--text)', whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>
                  {m.filename}
                </span>
                <Badge color={m.completeness_pct >= 80 ? 'var(--green)' : m.completeness_pct >= 50 ? 'var(--amber)' : 'var(--red)'}>
                  {Math.round(m.completeness_pct)}%
                </Badge>
              </div>
              <div style={{ marginTop:4, fontSize:10, color:'var(--muted)' }}>
                {m.required_present}/{m.required_total} fields · missing {(m.missing_fields || []).length}
              </div>
              <div style={{ marginTop:3, fontSize:10, color:'var(--muted)', whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>
                Matched: {m.matched_doc_filename || 'none'}
              </div>
              <div style={{ marginTop:2, fontSize:10, color:'var(--muted)' }}>
                Updated: {m.matched_doc_uploaded_at ? new Date(m.matched_doc_uploaded_at).toLocaleString() : '—'}
              </div>
            </div>
          ))}
          {shown.length === 0 && (
            <div style={{ fontSize:11, color:'var(--muted)' }}>No incomplete rows.</div>
          )}
        </div>
      )}
    </div>
  );
}

// ── AuditPanel ────────────────────────────────────────────────────────────────
function AuditPanel() {
  const [events, setEvents] = useState([]);
  const [open, setOpen] = useState(false);
  const load = async () => {
    const r = await api.get('/api/audit?limit=50');
    setEvents(r.data.events);
  };
  useEffect(() => { if(open) load(); }, [open]);
  const icons = { document_uploaded:<Upload size={12}/>, field_edited:<Edit3 size={12}/>, suggestion_actioned:<Sparkles size={12}/>, output_generated:<Download size={12}/>, upload_dedup:<RefreshCw size={12}/>, sample_loaded:<Database size={12}/> };
  return (
    <div className="audit-panel">
      <button className="audit-toggle" onClick={() => { setOpen(!open); if(!open) load(); }}>
        <Activity size={14} /> Audit Log <ChevronRight size={14} style={{ transform: open?'rotate(90deg)':'none', transition:'.2s' }} />
      </button>
      {open && (
        <div className="audit-list">
          {events.length === 0 && <div style={{ color:'var(--muted)', padding:'12px', fontSize:12 }}>No events yet.</div>}
          {events.map((e,i) => (
            <div key={i} className="audit-row">
              <span style={{ color:'var(--accent)', marginRight:4 }}>{icons[e.event]||<Clock size={12}/>}</span>
              <span style={{ fontFamily:'var(--mono)', fontSize:10, color:'var(--muted)', minWidth:160 }}>{e.ts?.slice(0,19).replace('T',' ')}</span>
              <span style={{ fontFamily:'var(--mono)', fontSize:11, color:'var(--text)', fontWeight:500 }}>{e.event}</span>
              {e.doc_id && <span style={{ fontSize:10, color:'var(--muted)', marginLeft:8 }}>…{e.doc_id.slice(-8)}</span>}
              {e.field && <span style={{ fontSize:10, color:'var(--purple)', marginLeft:8 }}>{e.field}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── HealthBadge ───────────────────────────────────────────────────────────────
function HealthBadge() {
  const [h, setH] = useState(null);
  useEffect(() => {
    api.get('/api/health').then(r => setH(r.data)).catch(()=>{});
  }, []);
  if (!h) return null;
  return (
    <div style={{ display:'flex', gap:6, alignItems:'center' }}>
      <Badge color={h.groq_available?'var(--green)':'var(--amber)'}>
        {h.groq_available ? '⚡ Groq' : '🔧 Heuristic'}
      </Badge>
      {h.pdf_available && <Badge color="var(--cyan)">PDF</Badge>}
      {h.docx_available && <Badge color="var(--cyan)">DOCX</Badge>}
    </div>
  );
}

// ── App ───────────────────────────────────────────────────────────────────────
export default function App() {
  const [docs, setDocs] = useState([]);
  const [pkgPct, setPkgPct] = useState(0);
  const [pkgData, setPkgData] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [uploadLoading, setUploadLoading] = useState(false);
  const [sampleLoading, setSampleLoading] = useState(false);

  const loadDocs = useCallback(async () => {
    const r = await api.get('/api/documents');
    const ordered = (r.data.documents || []).slice().sort((a,b) => {
      const ta = Date.parse(a.uploaded_at || '') || 0;
      const tb = Date.parse(b.uploaded_at || '') || 0;
      return tb - ta;
    });
    setDocs(ordered);
    setPkgPct(r.data.package_completeness_pct || 0);
    setPkgData(r.data.package || null);
    return ordered;
  }, []);

  useEffect(() => { loadDocs(); }, [loadDocs]);

  useEffect(() => {
    if (!selectedId && docs.length > 0) {
      setSelectedId(docs[0].doc_id);
    }
  }, [docs, selectedId]);

  const loadSample = async () => {
    setSampleLoading(true);
    const r = await api.post('/api/demo/load-sample');
    const ordered = await loadDocs();
    setSelectedId(r.data.doc_id || ordered?.[0]?.doc_id || null);
    setSampleLoading(false);
  };

  const handleUploaded = async () => {
    const ordered = await loadDocs();
    if (ordered?.length) setSelectedId(ordered[0].doc_id);
  };

  return (
    <div className="app">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <div style={{ display:'flex', alignItems:'center', gap:8 }}>
            <div className="logo-mark">M</div>
            <div>
              <div style={{ fontWeight:700, fontSize:15, letterSpacing:-.3 }}>MedDoc Intake</div>
              <div style={{ fontSize:10, color:'var(--muted)', letterSpacing:.5, textTransform:'uppercase' }}>POC · v0.1</div>
            </div>
          </div>
          <HealthBadge />
        </div>

        <UploadZone onUploaded={handleUploaded} loading={uploadLoading} setLoading={setUploadLoading} />

        <button className="btn-sample" onClick={loadSample} disabled={sampleLoading}>
          {sampleLoading ? <><RefreshCw size={13} className="spin"/> Loading…</> : <><Database size={13}/> Load Sample CEP</>}
        </button>

        {docs.length > 0 && <PackageSummary docs={docs} pkgPct={pkgPct} packageData={pkgData} />}

        <div className="doc-list">
          {docs.length === 0 && (
            <div style={{ color:'var(--muted)', fontSize:12, padding:'24px 0', textAlign:'center' }}>
              No documents yet.<br/>Upload a file or load the sample.
            </div>
          )}
          {docs.map(doc => (
            <DocCard key={doc.doc_id} doc={doc}
              selected={doc.doc_id === selectedId}
              onClick={() => setSelectedId(doc.doc_id)} />
          ))}
        </div>

        <AuditPanel />
      </aside>

      {/* Main */}
      <main className="main">
        {selectedId ? (
          <DocDetail docId={selectedId} onUpdate={loadDocs} />
        ) : (
          <div className="welcome">
            <div className="welcome-inner">
              <FileText size={48} strokeWidth={1} color="var(--border2)" />
              <h2>Document Intake & Review</h2>
              <p>Upload a regulatory document or load the sample Clinical Evaluation Protocol to get started.</p>
              <div style={{ display:'flex', gap:8, justifyContent:'center', marginTop:8 }}>
                <Badge color="var(--accent)">Extract fields</Badge>
                <Badge color="var(--amber)">Review suggestions</Badge>
                <Badge color="var(--green)">Generate output</Badge>
                <Badge color="var(--purple)">Full traceability</Badge>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
