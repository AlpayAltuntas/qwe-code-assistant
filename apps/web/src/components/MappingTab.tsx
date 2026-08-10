import { ChevronDown, Download, Layers, PlayCircle, Save, Trash2, Upload, Waypoints } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  applyMappingProfile,
  createMappingProfile,
  deleteMappingProfile,
  fetchSourceFields,
  fetchTargetFields,
  listMappingProfiles,
  type ApplyMappingResult,
  type FieldMapping,
  type FieldRef,
  type FieldSource,
  type LineSubfieldDef,
  type MappingFormat,
  type MappingProfile,
  type SourceField,
  type TargetFieldDef,
} from "../api";
import { Alert, Badge, Button, CodeBlock, EmptyState, SelectField, TextArea, TextField } from "./ui";

const FORMAT_OPTIONS = [
  { value: "edifact", label: "EDIFACT INVOIC" },
  { value: "ubl", label: "UBL Invoice" },
  { value: "cii", label: "CII (raw XML)" },
  { value: "zugferd", label: "ZUGFeRD / Factur-X (PDF)" },
];

function encodeRef(f: SourceField | FieldRef): string {
  return JSON.stringify({ parent_tag: f.parent_tag, tag: f.tag, occurrence: f.occurrence });
}

function decodeRef(key: string): FieldRef {
  return JSON.parse(key) as FieldRef;
}

function downloadBlob(filename: string, content: string, mimeType: string, isBase64 = false) {
  const blob = isBase64
    ? new Blob([Uint8Array.from(atob(content), (c) => c.charCodeAt(0))], { type: mimeType })
    : new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve((reader.result as string).split(",")[1] ?? "");
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

/** One target field's source: a dropdown of candidate source fields, or a
 * constant value — toggled by two small mode buttons. */
function SourceFieldSelector({
  value,
  onChange,
  options,
}: {
  value: FieldSource | undefined;
  onChange: (v: FieldSource | undefined) => void;
  options: SourceField[];
}) {
  const mode = value?.kind ?? "field";
  return (
    <div className="mapping-control">
      <div className="mode-toggle">
        <button
          type="button"
          className={mode === "field" ? "active" : ""}
          onClick={() => value?.kind === "constant" && onChange(undefined)}
        >
          Field
        </button>
        <button
          type="button"
          className={mode === "constant" ? "active" : ""}
          onClick={() => onChange({ kind: "constant", value: value?.kind === "constant" ? value.value : "" })}
        >
          Constant
        </button>
      </div>
      {mode === "field" ? (
        <div className="select-wrap">
          <select
            className="select"
            value={value?.kind === "field" ? encodeRef(value.ref) : ""}
            onChange={(e) => onChange(e.target.value ? { kind: "field", ref: decodeRef(e.target.value) } : undefined)}
          >
            <option value="">— none —</option>
            {options.map((o) => (
              <option key={encodeRef(o)} value={encodeRef(o)}>
                {o.label}
              </option>
            ))}
          </select>
          <ChevronDown size={13} />
        </div>
      ) : (
        <input
          className="input"
          placeholder="constant value"
          value={value?.kind === "constant" ? value.value : ""}
          onChange={(e) => onChange({ kind: "constant", value: e.target.value })}
        />
      )}
    </div>
  );
}

/** Sample/apply document input: textarea for text-based formats, a
 * dropzone (base64-encoding) for ZUGFeRD's PDF. */
function DocumentInput({
  format,
  value,
  onChange,
  placeholder,
}: {
  format: MappingFormat;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  const [fileName, setFileName] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  if (format !== "zugferd") {
    return (
      <TextArea
        placeholder={placeholder}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setFileName(null);
        }}
        rows={6}
      />
    );
  }

  return (
    <div
      className="dropzone"
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => e.preventDefault()}
      onDrop={async (e) => {
        e.preventDefault();
        const file = e.dataTransfer.files?.[0];
        if (file) {
          setFileName(file.name);
          onChange(await fileToBase64(file));
        }
      }}
    >
      <Upload size={18} strokeWidth={1.75} />
      {fileName ? <span className="file-chip">{fileName}</span> : <span>Drop a PDF here, or click to browse</span>}
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf"
        onChange={async (e) => {
          const file = e.target.files?.[0];
          if (file) {
            setFileName(file.name);
            onChange(await fileToBase64(file));
          }
        }}
      />
    </div>
  );
}

export function MappingTab() {
  const [fromFormat, setFromFormat] = useState<MappingFormat>("edifact");
  const [toFormat, setToFormat] = useState<MappingFormat>("ubl");

  const [sampleContent, setSampleContent] = useState("");
  const [headerFields, setHeaderFields] = useState<SourceField[]>([]);
  const [lineTemplateFields, setLineTemplateFields] = useState<SourceField[]>([]);
  const [lineCount, setLineCount] = useState(0);
  const [targetDefs, setTargetDefs] = useState<{
    header: TargetFieldDef[];
    lineSubfields: LineSubfieldDef[];
  } | null>(null);

  const [headerSources, setHeaderSources] = useState<Record<string, FieldSource | undefined>>({});
  const [lineSources, setLineSources] = useState<Record<string, FieldSource | undefined>>({});
  const [profileName, setProfileName] = useState("");

  const [profiles, setProfiles] = useState<MappingProfile[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState<number | null>(null);
  const [applyContent, setApplyContent] = useState("");
  const [applyResult, setApplyResult] = useState<ApplyMappingResult | null>(null);

  const [loadingFields, setLoadingFields] = useState(false);
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchTargetFields().then(setTargetDefs).catch((err) => setError(String(err)));
    refreshProfiles();
  }, []);

  // Changing the source format invalidates any fields/mappings already
  // built against the old format's addressing scheme.
  useEffect(() => {
    setHeaderFields([]);
    setLineTemplateFields([]);
    setLineCount(0);
    setHeaderSources({});
    setLineSources({});
    setSampleContent("");
  }, [fromFormat]);

  async function refreshProfiles() {
    try {
      setProfiles(await listMappingProfiles());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleLoadFields() {
    if (!sampleContent.trim()) {
      setError("Provide a sample message first.");
      return;
    }
    setLoadingFields(true);
    setError(null);
    try {
      const { header, lineTemplate, lineCount: count } = await fetchSourceFields(sampleContent, fromFormat);
      setHeaderFields(header);
      setLineTemplateFields(lineTemplate);
      setLineCount(count);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingFields(false);
    }
  }

  const groupedHeaderFields = useMemo(() => {
    if (!targetDefs) return [];
    const groups = new Map<string, TargetFieldDef[]>();
    for (const t of targetDefs.header) {
      if (!groups.has(t.group)) groups.set(t.group, []);
      groups.get(t.group)!.push(t);
    }
    return [...groups.entries()];
  }, [targetDefs]);

  function buildFieldMappings(): FieldMapping[] {
    const mappings: FieldMapping[] = [];
    for (const [field, source] of Object.entries(headerSources)) {
      if (source) mappings.push({ target_field: field, source });
    }
    for (const [subfield, source] of Object.entries(lineSources)) {
      if (source) mappings.push({ target_field: `line.${subfield}`, source });
    }
    return mappings;
  }

  async function handleSaveProfile() {
    if (!profileName.trim()) {
      setError("Name the mapping before saving.");
      return;
    }
    setSaving(true);
    setError(null);
    setSaveMessage(null);
    try {
      const created = await createMappingProfile({
        name: profileName,
        fromFormat,
        toFormat,
        fieldMappings: buildFieldMappings(),
      });
      setSaveMessage(`Saved "${created.name}".`);
      setSelectedProfileId(created.id);
      await refreshProfiles();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteProfile(id: number) {
    await deleteMappingProfile(id);
    if (selectedProfileId === id) setSelectedProfileId(null);
    await refreshProfiles();
  }

  const selectedProfile = profiles.find((p) => p.id === selectedProfileId) ?? null;

  async function handleApply() {
    if (!selectedProfileId) {
      setError("Pick a saved mapping first.");
      return;
    }
    if (!applyContent.trim()) {
      setError("Provide a document to apply the mapping to.");
      return;
    }
    setApplying(true);
    setError(null);
    setApplyResult(null);
    try {
      setApplyResult(await applyMappingProfile(selectedProfileId, applyContent));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setApplying(false);
    }
  }

  function handleDownloadResult() {
    if (!applyResult?.content) return;
    const ext = applyResult.format === "zugferd" ? "pdf" : "xml";
    const filename = `mapped-invoice.${ext}`;
    if (applyResult.encoding === "base64") {
      downloadBlob(filename, applyResult.content, "application/pdf", true);
    } else {
      downloadBlob(filename, applyResult.content, "text/plain");
    }
  }

  const hasFields = headerFields.length > 0;

  return (
    <div>
      {error && (
        <div style={{ marginBottom: 20 }}>
          <Alert variant="danger">{error}</Alert>
        </div>
      )}

      <div className="form-row">
        <SelectField
          label="From format"
          value={fromFormat}
          onChange={(e) => setFromFormat(e.target.value as MappingFormat)}
          options={FORMAT_OPTIONS}
        />
        <SelectField
          label="To format"
          value={toFormat}
          onChange={(e) => setToFormat(e.target.value as MappingFormat)}
          options={FORMAT_OPTIONS}
        />
      </div>

      <div className="section-heading">
        <span className="step-badge">1</span> Load fields from a sample message
      </div>
      <DocumentInput
        format={fromFormat}
        value={sampleContent}
        onChange={setSampleContent}
        placeholder="Paste a sample message…"
      />
      <div className="form-actions">
        <Button loading={loadingFields} onClick={handleLoadFields}>
          Load fields
        </Button>
        {hasFields && (
          <>
            <Badge variant="info">{headerFields.length} header fields</Badge>
            <Badge variant="info">{lineTemplateFields.length} line-template fields</Badge>
            <Badge variant="neutral">{lineCount} line item{lineCount === 1 ? "" : "s"} in sample</Badge>
          </>
        )}
      </div>

      {targetDefs && hasFields && (
        <>
          <div className="section-heading">
            <span className="step-badge">2</span> Map header fields
          </div>
          {groupedHeaderFields.map(([group, fields]) => (
            <div key={group} className="field-group">
              <div className="field-group-title">{group}</div>
              <div className="table-scroll">
                <table className="table">
                  <tbody>
                    {fields.map((t) => (
                      <tr key={t.field}>
                        <td style={{ width: "32%" }}>{t.label}</td>
                        <td>
                          <SourceFieldSelector
                            value={headerSources[t.field]}
                            onChange={(v) => setHeaderSources({ ...headerSources, [t.field]: v })}
                            options={headerFields}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}

          <div className="section-heading">
            <span className="step-badge">3</span> Map line items
          </div>
          <p className="hint" style={{ marginTop: -4 }}>
            <Layers size={12} style={{ verticalAlign: -2, marginRight: 4 }} />
            One template, applied to every line-item group a target document has — not just the{" "}
            {lineCount} in this sample.
          </p>
          <div className="table-scroll">
            <table className="table">
              <tbody>
                {targetDefs.lineSubfields.map((t) => (
                  <tr key={t.subfield}>
                    <td style={{ width: "32%" }}>{t.label}</td>
                    <td>
                      <SourceFieldSelector
                        value={lineSources[t.subfield]}
                        onChange={(v) => setLineSources({ ...lineSources, [t.subfield]: v })}
                        options={lineTemplateFields}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="section-heading">
            <span className="step-badge">4</span> Save
          </div>
          <div className="form-row">
            <TextField
              label="Mapping name"
              placeholder="e.g. Acme supplier EDIFACT → UBL"
              value={profileName}
              onChange={(e) => setProfileName(e.target.value)}
              style={{ width: 320 }}
            />
          </div>
          <div className="form-actions">
            <Button variant="primary" icon={<Save size={14} />} loading={saving} onClick={handleSaveProfile}>
              Save mapping
            </Button>
            {saveMessage && <span className="hint" style={{ margin: 0 }}>{saveMessage}</span>}
          </div>
        </>
      )}

      <hr className="divider" />

      <div className="section-heading">Saved mappings</div>
      {profiles.length === 0 ? (
        <EmptyState
          icon={<Waypoints size={26} strokeWidth={1.5} />}
          title="No saved mappings yet"
          description="Build one above from a sample message."
        />
      ) : (
        <div className="profile-list">
          {profiles.map((p) => (
            <div
              key={p.id}
              className={`profile-card ${selectedProfileId === p.id ? "selected" : ""}`}
              onClick={() => setSelectedProfileId(p.id)}
            >
              <div>
                <div className="profile-card-name">{p.name}</div>
                <div className="profile-card-meta">
                  {p.fromFormat} → {p.toFormat} · {p.fieldMappings.length} field
                  {p.fieldMappings.length === 1 ? "" : "s"} mapped
                </div>
              </div>
              <div className="profile-card-actions">
                <button
                  className="icon-btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDeleteProfile(p.id);
                  }}
                  title="Delete mapping"
                  type="button"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {profiles.length > 0 && (
        <>
          <div className="section-heading">Apply a saved mapping</div>
          {!selectedProfileId && <p className="hint">Select a mapping above first.</p>}
          {selectedProfile && (
            <DocumentInput
              format={selectedProfile.fromFormat}
              value={applyContent}
              onChange={setApplyContent}
              placeholder={`Paste a ${selectedProfile.fromFormat} document to convert — any number of line items…`}
            />
          )}
          <div className="form-actions">
            <Button
              variant="primary"
              icon={<PlayCircle size={15} />}
              loading={applying}
              disabled={!selectedProfileId}
              onClick={handleApply}
            >
              Apply mapping
            </Button>
          </div>

          {applyResult && (
            <div style={{ marginTop: 20 }}>
              {applyResult.error && <Alert variant="danger">{applyResult.error}</Alert>}
              {applyResult.notes && applyResult.notes.length > 0 && (
                <ul className="findings">
                  {applyResult.notes.map((n, i) => (
                    <li key={i} className="finding-row finding-row-warning">
                      {n}
                    </li>
                  ))}
                </ul>
              )}
              {applyResult.content && (
                <>
                  <div className="result-header">
                    <div className="result-header-left">
                      {applyResult.format && <Badge variant="info">{applyResult.format}</Badge>}
                    </div>
                    {applyResult.encoding === "base64" && (
                      <Button size="sm" icon={<Download size={14} />} onClick={handleDownloadResult}>
                        Download
                      </Button>
                    )}
                  </div>
                  {applyResult.encoding === "base64" ? (
                    <>
                      <p className="hint">
                        Base64-encoded PDF/A-3. The visual layer is a blank placeholder — the embedded
                        CII XML below is the authoritative content.
                      </p>
                      {applyResult.cii_xml && <CodeBlock content={applyResult.cii_xml} label="Embedded CII XML" />}
                    </>
                  ) : (
                    <CodeBlock content={applyResult.content} label={applyResult.format ?? "output"} />
                  )}
                </>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
