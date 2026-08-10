import { AlertTriangle, CheckCircle2, Download, FilePlus2, PlusCircle, Trash2, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  buildDocument,
  fetchTargetFields,
  type BuildDocumentResult,
  type LineSubfieldDef,
  type MappingFormat,
  type TargetFieldDef,
} from "../api";
import { Alert, Badge, Button, CodeBlock, EmptyState, SelectField, TextField } from "./ui";

const FORMAT_OPTIONS = [
  { value: "edifact", label: "EDIFACT INVOIC" },
  { value: "ubl", label: "UBL Invoice" },
  { value: "cii", label: "CII (raw XML)" },
  { value: "zugferd", label: "ZUGFeRD / Factur-X (PDF)" },
];

const FINDING_ICON = {
  error: <XCircle size={14} />,
  warning: <AlertTriangle size={14} />,
  info: <CheckCircle2 size={14} />,
};

const FORMAT_FILE_INFO: Record<MappingFormat, { ext: string; mimeType: string }> = {
  edifact: { ext: "edi", mimeType: "application/edifact" },
  ubl: { ext: "xml", mimeType: "application/xml" },
  cii: { ext: "xml", mimeType: "application/xml" },
  zugferd: { ext: "pdf", mimeType: "application/pdf" },
};

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

let nextLineKey = 1;

interface LineRow {
  key: number;
  values: Record<string, string>;
}

function emptyLine(): LineRow {
  return { key: nextLineKey++, values: {} };
}

export function CreateTab() {
  const [toFormat, setToFormat] = useState<MappingFormat>("ubl");
  const [targetDefs, setTargetDefs] = useState<{ header: TargetFieldDef[]; lineSubfields: LineSubfieldDef[] } | null>(
    null,
  );
  const [header, setHeader] = useState<Record<string, string>>({});
  const [lines, setLines] = useState<LineRow[]>([emptyLine()]);

  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BuildDocumentResult | null>(null);

  useEffect(() => {
    fetchTargetFields()
      .then(setTargetDefs)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const groupedHeaderFields = useMemo(() => {
    if (!targetDefs) return [];
    const groups = new Map<string, TargetFieldDef[]>();
    for (const t of targetDefs.header) {
      if (!groups.has(t.group)) groups.set(t.group, []);
      groups.get(t.group)!.push(t);
    }
    return [...groups.entries()];
  }, [targetDefs]);

  function setHeaderField(field: string, value: string) {
    setHeader((prev) => {
      if (value) return { ...prev, [field]: value };
      const { [field]: _omit, ...rest } = prev;
      return rest;
    });
  }

  function setLineField(key: number, subfield: string, value: string) {
    setLines((prev) =>
      prev.map((line) => {
        if (line.key !== key) return line;
        const values = value
          ? { ...line.values, [subfield]: value }
          : Object.fromEntries(Object.entries(line.values).filter(([k]) => k !== subfield));
        return { ...line, values };
      }),
    );
  }

  function addLine() {
    setLines((prev) => [...prev, emptyLine()]);
  }

  function removeLine(key: number) {
    setLines((prev) => (prev.length > 1 ? prev.filter((l) => l.key !== key) : prev));
  }

  async function handleGenerate() {
    setGenerating(true);
    setError(null);
    setResult(null);
    try {
      const nonEmptyLines = lines.map((l) => l.values).filter((v) => Object.keys(v).length > 0);
      setResult(
        await buildDocument({
          header,
          lines: nonEmptyLines,
          toFormat,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(false);
    }
  }

  function handleDownload() {
    if (!result?.content || !result.format) return;
    const { ext, mimeType } = FORMAT_FILE_INFO[result.format];
    const filename = `invoice.${ext}`;
    downloadBlob(filename, result.content, mimeType, result.encoding === "base64");
  }

  return (
    <div>
      {error && (
        <div style={{ marginBottom: 20 }}>
          <Alert variant="danger">{error}</Alert>
        </div>
      )}

      <div className="form-row">
        <SelectField
          label="Target format"
          value={toFormat}
          onChange={(e) => setToFormat(e.target.value as MappingFormat)}
          options={FORMAT_OPTIONS}
        />
      </div>

      {targetDefs && (
        <>
          <div className="section-heading">
            <span className="step-badge">1</span> Header fields
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
                          <input
                            className="input"
                            value={header[t.field] ?? ""}
                            onChange={(e) => setHeaderField(t.field, e.target.value)}
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
            <span className="step-badge">2</span> Line items
          </div>
          <div className="line-item-list">
            {lines.map((line, idx) => (
              <div key={line.key} className="line-item-card">
                <div className="line-item-card-header">
                  <span className="line-item-index">Line {idx + 1}</span>
                  {lines.length > 1 && (
                    <button className="icon-btn" type="button" title="Remove line" onClick={() => removeLine(line.key)}>
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
                      onChange={(e) => setLineField(line.key, s.subfield, e.target.value)}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div className="form-actions">
            <Button size="sm" icon={<PlusCircle size={14} />} onClick={addLine}>
              Add line item
            </Button>
          </div>

          <div className="section-heading">
            <span className="step-badge">3</span> Generate
          </div>
          <div className="form-actions">
            <Button variant="primary" icon={<FilePlus2 size={15} />} loading={generating} onClick={handleGenerate}>
              Generate document
            </Button>
          </div>
        </>
      )}

      {!targetDefs && !error && (
        <EmptyState icon={<FilePlus2 size={26} strokeWidth={1.5} />} title="Loading fields…" description="" />
      )}

      {result && (
        <div style={{ marginTop: 20 }}>
          {result.error && <Alert variant="danger">{result.error}</Alert>}

          {result.notes && result.notes.length > 0 && (
            <ul className="findings">
              {result.notes.map((n, i) => (
                <li key={i} className="finding-row finding-row-warning">
                  {n}
                </li>
              ))}
            </ul>
          )}

          {result.validation && result.validation.length > 0 && (
            <ul className="findings">
              {result.validation.map((f, i) => (
                <li key={i} className={`finding-row finding-row-${f.level}`}>
                  <span className="finding-icon">
                    {FINDING_ICON[f.level as keyof typeof FINDING_ICON] ?? FINDING_ICON.info}
                  </span>
                  <span>
                    <span className="finding-code">{f.code}</span>
                    <span className="finding-message">{f.message}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}

          {result.content && (
            <>
              <div className="result-header">
                <div className="result-header-left">{result.format && <Badge variant="info">{result.format}</Badge>}</div>
                <Button size="sm" icon={<Download size={14} />} onClick={handleDownload}>
                  Download {result.format ? FORMAT_FILE_INFO[result.format].ext.toUpperCase() : "file"}
                </Button>
              </div>
              {result.encoding === "base64" ? (
                <>
                  <p className="hint">
                    Base64-encoded PDF/A-3. The visual layer is a blank placeholder — the embedded CII XML below
                    is the authoritative content.
                  </p>
                  {result.cii_xml && <CodeBlock content={result.cii_xml} label="Embedded CII XML" />}
                </>
              ) : (
                <CodeBlock content={result.content} label={result.format ?? "output"} />
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
