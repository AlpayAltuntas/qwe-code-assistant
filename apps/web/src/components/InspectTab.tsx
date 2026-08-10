import { AlertTriangle, CheckCircle2, FileSearch, Upload, XCircle } from "lucide-react";
import { type DragEvent, useRef, useState } from "react";
import {
  parseInvoice,
  validateInvoice,
  type EdiFormat,
  type ParseResponse,
  type ValidateResponse,
} from "../api";
import { Alert, Badge, Button, EmptyState, SelectField, TextArea } from "./ui";

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve((reader.result as string).split(",")[1] ?? "");
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

const FORMAT_OPTIONS = [
  { value: "edifact", label: "EDIFACT INVOIC" },
  { value: "ubl", label: "UBL Invoice" },
  { value: "cii", label: "CII (raw XML)" },
  { value: "zugferd", label: "ZUGFeRD / Factur-X (PDF)" },
];

const FINDING_ICON = { error: <XCircle size={14} />, warning: <AlertTriangle size={14} />, info: <CheckCircle2 size={14} /> };

export function InspectTab() {
  const [format, setFormat] = useState<EdiFormat>("edifact");
  const [content, setContent] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [parseResult, setParseResult] = useState<ParseResponse | null>(null);
  const [validateResult, setValidateResult] = useState<ValidateResponse | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function loadFile(file: File) {
    setFileName(file.name);
    setContent(format === "zugferd" ? await fileToBase64(file) : await file.text());
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) loadFile(file);
  }

  async function handleAnalyze() {
    if (!content.trim()) {
      setError("Paste or upload some content first.");
      return;
    }
    setLoading(true);
    setError(null);
    setParseResult(null);
    setValidateResult(null);
    try {
      const [parsed, validated] = await Promise.all([
        parseInvoice({ content, format }),
        validateInvoice({ content, format }),
      ]);
      setParseResult(parsed);
      setValidateResult(validated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  const verdict = validateResult?.verdict ?? (validateResult?.error ? "error" : null);

  return (
    <div>
      <div className="form-row">
        <SelectField
          label="Format"
          value={format}
          onChange={(e) => {
            setFormat(e.target.value as EdiFormat);
            setFileName(null);
          }}
          options={FORMAT_OPTIONS}
        />
      </div>

      <div
        className="dropzone"
        onClick={() => fileInputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        style={dragOver ? { borderColor: "var(--accent)", background: "var(--accent-subtle)" } : undefined}
      >
        <Upload size={18} strokeWidth={1.75} />
        {fileName ? (
          <span className="file-chip">{fileName}</span>
        ) : (
          <span>Drop a file here, or click to browse</span>
        )}
        <input
          ref={fileInputRef}
          type="file"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) loadFile(file);
          }}
        />
      </div>

      {format !== "zugferd" && (
        <div style={{ marginTop: 12 }}>
          <TextArea
            placeholder="…or paste EDIFACT / UBL / CII content here"
            value={content}
            onChange={(e) => {
              setContent(e.target.value);
              setFileName(null);
            }}
            rows={7}
          />
        </div>
      )}

      <div className="form-actions">
        <Button variant="primary" icon={<FileSearch size={15} />} loading={loading} onClick={handleAnalyze}>
          Analyze
        </Button>
      </div>

      {error && (
        <div style={{ marginTop: 20 }}>
          <Alert variant="danger">{error}</Alert>
        </div>
      )}

      {!validateResult && !parseResult && !loading && !error && (
        <>
          <div className="section-heading">Result</div>
          <EmptyState
            icon={<FileSearch size={28} strokeWidth={1.5} />}
            title="Nothing analyzed yet"
            description="The validation verdict is always deterministic — real schema/structural checks, never a model's guess."
          />
        </>
      )}

      {validateResult && (
        <>
          <div className="section-heading">Validation</div>
          <div className="result-header">
            <div className="result-header-left">
              {verdict === "valid" && <Badge variant="success" icon>valid</Badge>}
              {verdict === "invalid" && <Badge variant="danger" icon>invalid</Badge>}
              {verdict === "error" && <Badge variant="warning" icon>error</Badge>}
            </div>
          </div>

          {validateResult.error && <Alert variant="warning">{validateResult.error}</Alert>}

          {validateResult.findings && (
            <ul className="findings">
              {validateResult.findings.map((f, i) => (
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

          {validateResult.citations && validateResult.citations.length > 0 && (
            <>
              <div className="section-heading" style={{ marginTop: 20 }}>
                Cited spec references
              </div>
              <ul className="citations">
                {validateResult.citations.map((c, i) => (
                  <li key={i} className="citation-card">
                    <span className="citation-doc">
                      <code>{c.doc_id}</code> § {c.section}
                    </span>
                    <span className="citation-score">{Math.round(c.score * 100)}%</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}

      {parseResult && (parseResult.segments || parseResult.elements) && (
        <>
          <div className="section-heading">Segment breakdown</div>
          <div className="table-scroll">
            {parseResult.segments && (
              <table className="table">
                <thead>
                  <tr>
                    <th>Tag</th>
                    <th>Description</th>
                    <th>Elements</th>
                  </tr>
                </thead>
                <tbody>
                  {parseResult.segments.map((s, i) => (
                    <tr key={i}>
                      <td>
                        <code>{s.tag}</code>
                      </td>
                      <td>{s.description}</td>
                      <td className="mono-small">{JSON.stringify(s.elements)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {parseResult.elements && (
              <table className="table">
                <thead>
                  <tr>
                    <th>Path</th>
                    <th>Text</th>
                  </tr>
                </thead>
                <tbody>
                  {parseResult.elements.map((el, i) => (
                    <tr key={i}>
                      <td className="mono-small">{el.path}</td>
                      <td>{el.text}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}
