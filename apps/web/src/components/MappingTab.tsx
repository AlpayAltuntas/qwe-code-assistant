import { Download, FilePlus2, PlayCircle, PlusCircle, Save, Trash2, Upload, Waypoints } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  applyMappingProfile,
  buildDocument,
  createMappingProfile,
  deleteMappingProfile,
  fetchSourceFields,
  fetchTargetFields,
  listMappingProfiles,
  type ApplyMappingResult,
  type FieldMapping,
  type FieldSource,
  type LineSubfieldDef,
  type MappingFormat,
  type MappingProfile,
  type SourceField,
  type TargetFieldDef,
} from "../api";
import { type CanvasTargetSection, FieldMappingCanvas } from "./FieldMappingCanvas";
import { Alert, Badge, Button, CodeBlock, EmptyState, SelectField, TextArea, TextField } from "./ui";

const FORMAT_OPTIONS = [
  { value: "edifact", label: "EDIFACT INVOIC" },
  { value: "ubl", label: "UBL Invoice" },
  { value: "cii", label: "CII (raw XML)" },
  { value: "zugferd", label: "ZUGFeRD / Factur-X (PDF)" },
];

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

const FORMAT_FILE_INFO: Record<MappingFormat, { ext: string; mimeType: string }> = {
  edifact: { ext: "edi", mimeType: "application/edifact" },
  ubl: { ext: "xml", mimeType: "application/xml" },
  cii: { ext: "xml", mimeType: "application/xml" },
  zugferd: { ext: "pdf", mimeType: "application/pdf" },
};

let nextManualLineKey = 1;

interface ManualLineRow {
  key: number;
  values: Record<string, string>;
}

function emptyManualLine(): ManualLineRow {
  return { key: nextManualLineKey++, values: {} };
}

/** A saved mapping's constant-sourced fields need no source document at
 * all — carry them over as a starting point when switching into manual
 * entry, so the user only has to fill in what the mapping couldn't
 * already fix. */
function constantsFromProfile(profile: MappingProfile): { header: Record<string, string>; line: Record<string, string> } {
  const header: Record<string, string> = {};
  const line: Record<string, string> = {};
  for (const m of profile.fieldMappings) {
    if (m.source.kind !== "constant") continue;
    if (m.target_field.startsWith("line.")) {
      line[m.target_field.slice("line.".length)] = m.source.value;
    } else {
      header[m.target_field] = m.source.value;
    }
  }
  return { header, line };
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve((reader.result as string).split(",")[1] ?? "");
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
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
  const [applyMode, setApplyMode] = useState<"document" | "manual">("document");
  const [manualHeader, setManualHeader] = useState<Record<string, string>>({});
  const [manualLines, setManualLines] = useState<ManualLineRow[]>([emptyManualLine()]);

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

  // Selecting a different saved mapping invalidates whatever apply
  // state (document or manual entry) was built against the previous one.
  useEffect(() => {
    const profile = profiles.find((p) => p.id === selectedProfileId);
    setApplyContent("");
    setApplyResult(null);
    setApplyMode("document");
    if (profile) {
      const { header, line } = constantsFromProfile(profile);
      setManualHeader(header);
      setManualLines([{ key: nextManualLineKey++, values: line }]);
    } else {
      setManualHeader({});
      setManualLines([emptyManualLine()]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProfileId]);

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

  const headerTargetSections: CanvasTargetSection[] = useMemo(
    () => groupedHeaderFields.map(([group, fields]) => ({ title: group, fields })),
    [groupedHeaderFields],
  );

  const lineTargetSections: CanvasTargetSection[] = useMemo(
    () => [
      {
        title: null,
        fields: (targetDefs?.lineSubfields ?? []).map((s) => ({ field: s.subfield, label: s.label })),
      },
    ],
    [targetDefs],
  );

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

  function handleDownloadProfile(p: MappingProfile) {
    const portable = { name: p.name, fromFormat: p.fromFormat, toFormat: p.toFormat, fieldMappings: p.fieldMappings };
    const filename = `${p.name.trim().replace(/[^a-z0-9-_]+/gi, "-").toLowerCase() || "mapping"}.json`;
    downloadBlob(filename, JSON.stringify(portable, null, 2), "application/json");
  }

  const selectedProfile = profiles.find((p) => p.id === selectedProfileId) ?? null;

  // A profile whose fromFormat matches what's currently loaded in step 1
  // shares that same document — no reason to make the user paste the
  // same source document twice just to apply the mapping they built it
  // for. Editing either box edits the same underlying state; only a
  // profile expecting a different format falls back to its own content.
  const sampleReusable = selectedProfile !== null && selectedProfile.fromFormat === fromFormat;
  const effectiveApplyContent = sampleReusable ? sampleContent : applyContent;
  const setEffectiveApplyContent = sampleReusable ? setSampleContent : setApplyContent;

  async function handleApply() {
    if (!selectedProfileId) {
      setError("Pick a saved mapping first.");
      return;
    }
    if (!effectiveApplyContent.trim()) {
      setError("Provide a document to apply the mapping to.");
      return;
    }
    setApplying(true);
    setError(null);
    setApplyResult(null);
    try {
      setApplyResult(await applyMappingProfile(selectedProfileId, effectiveApplyContent));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setApplying(false);
    }
  }

  function setManualHeaderField(field: string, value: string) {
    setManualHeader((prev) => {
      if (value) return { ...prev, [field]: value };
      const { [field]: _omit, ...rest } = prev;
      return rest;
    });
  }

  function setManualLineField(key: number, subfield: string, value: string) {
    setManualLines((prev) =>
      prev.map((line) => {
        if (line.key !== key) return line;
        const values = value
          ? { ...line.values, [subfield]: value }
          : Object.fromEntries(Object.entries(line.values).filter(([k]) => k !== subfield));
        return { ...line, values };
      }),
    );
  }

  function addManualLine() {
    setManualLines((prev) => [...prev, emptyManualLine()]);
  }

  function removeManualLine(key: number) {
    setManualLines((prev) => (prev.length > 1 ? prev.filter((l) => l.key !== key) : prev));
  }

  async function handleManualGenerate() {
    if (!selectedProfile) {
      setError("Pick a saved mapping first.");
      return;
    }
    setApplying(true);
    setError(null);
    setApplyResult(null);
    try {
      const nonEmptyLines = manualLines.map((l) => l.values).filter((v) => Object.keys(v).length > 0);
      setApplyResult(
        await buildDocument({
          header: manualHeader,
          lines: nonEmptyLines,
          toFormat: selectedProfile.toFormat,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setApplying(false);
    }
  }

  function handleDownloadResult() {
    if (!applyResult?.content || !applyResult.format) return;
    const { ext, mimeType } = FORMAT_FILE_INFO[applyResult.format];
    const filename = `mapped-invoice.${ext}`;
    downloadBlob(filename, applyResult.content, mimeType, applyResult.encoding === "base64");
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
          <p className="hint" style={{ marginTop: -4 }}>
            Drag a source field onto a target field to connect them — or click a source field, then
            click a target field. Click a target's value to type a constant instead.
          </p>
          <FieldMappingCanvas
            sourceFields={headerFields}
            targetSections={headerTargetSections}
            values={headerSources}
            onChange={(field, source) => setHeaderSources((prev) => ({ ...prev, [field]: source }))}
            sourceHeading={`Source (${fromFormat}) — ${headerFields.length} fields`}
            targetHeading={`Target (${toFormat}) — header`}
          />

          <div className="section-heading">
            <span className="step-badge">3</span> Map line items
          </div>
          <p className="hint" style={{ marginTop: -4 }}>
            One template, applied to every line-item group a target document has — not just the{" "}
            {lineCount} in this sample.
          </p>
          <FieldMappingCanvas
            sourceFields={lineTemplateFields}
            targetSections={lineTargetSections}
            values={lineSources}
            onChange={(field, source) => setLineSources((prev) => ({ ...prev, [field]: source }))}
            sourceHeading={`Source (${fromFormat}) — line template`}
            targetHeading={`Target (${toFormat}) — line items`}
          />

          <div className="section-heading">
            <span className="step-badge">4</span> Save
          </div>
          <p className="hint" style={{ marginTop: -4 }}>
            You need to save the mapping before it can be used to create a document.
          </p>
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
                  className="icon-btn icon-btn-neutral"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDownloadProfile(p);
                  }}
                  title="Download mapping"
                  type="button"
                >
                  <Download size={14} />
                </button>
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
            <>
              <div className="mode-toggle" style={{ marginBottom: 14 }}>
                <button
                  type="button"
                  className={applyMode === "document" ? "active" : ""}
                  onClick={() => setApplyMode("document")}
                >
                  From a document
                </button>
                <button
                  type="button"
                  className={applyMode === "manual" ? "active" : ""}
                  onClick={() => setApplyMode("manual")}
                >
                  Enter values manually
                </button>
              </div>

              {applyMode === "document" ? (
                <>
                  {sampleReusable && sampleContent && (
                    <p className="hint" style={{ marginTop: -4 }}>
                      Reusing the sample document loaded in step 1 — edit it below if you want to apply
                      to something else.
                    </p>
                  )}
                  <DocumentInput
                    format={selectedProfile.fromFormat}
                    value={effectiveApplyContent}
                    onChange={setEffectiveApplyContent}
                    placeholder={`Paste a ${selectedProfile.fromFormat} document to convert — any number of line items…`}
                  />
                  <div className="form-actions">
                    <Button variant="primary" icon={<PlayCircle size={15} />} loading={applying} onClick={handleApply}>
                      Apply mapping
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  <p className="hint" style={{ marginTop: -4 }}>
                    No source document — type the values directly and build a {selectedProfile.toFormat} document.
                    {Object.keys(manualHeader).length > 0 || Object.values(manualLines[0]?.values ?? {}).length > 0
                      ? " Fields already fixed to a constant in this mapping are pre-filled below."
                      : ""}
                  </p>
                  {targetDefs && (
                    <>
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
                                      <input
                                        className="input"
                                        value={manualHeader[t.field] ?? ""}
                                        onChange={(e) => setManualHeaderField(t.field, e.target.value)}
                                      />
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      ))}

                      <div className="field-group-title">Line items</div>
                      <div className="line-item-list">
                        {manualLines.map((line, idx) => (
                          <div key={line.key} className="line-item-card">
                            <div className="line-item-card-header">
                              <span className="line-item-index">Line {idx + 1}</span>
                              {manualLines.length > 1 && (
                                <button
                                  className="icon-btn"
                                  type="button"
                                  title="Remove line"
                                  onClick={() => removeManualLine(line.key)}
                                >
                                  <Trash2 size={14} />
                                </button>
                              )}
                            </div>
                            <div className="line-item-grid">
                              {targetDefs.lineSubfields.map((s) => (
                                <TextField
                                  key={s.subfield}
                                  label={s.label}
                                  value={line.values[s.subfield] ?? ""}
                                  onChange={(e) => setManualLineField(line.key, s.subfield, e.target.value)}
                                />
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                      <div className="form-actions">
                        <Button size="sm" icon={<PlusCircle size={14} />} onClick={addManualLine}>
                          Add line item
                        </Button>
                      </div>
                    </>
                  )}
                  <div className="form-actions">
                    <Button
                      variant="primary"
                      icon={<FilePlus2 size={15} />}
                      loading={applying}
                      onClick={handleManualGenerate}
                    >
                      Generate document
                    </Button>
                  </div>
                </>
              )}
            </>
          )}

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
                    <Button size="sm" icon={<Download size={14} />} onClick={handleDownloadResult}>
                      Download {applyResult.format ? FORMAT_FILE_INFO[applyResult.format].ext.toUpperCase() : "file"}
                    </Button>
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
