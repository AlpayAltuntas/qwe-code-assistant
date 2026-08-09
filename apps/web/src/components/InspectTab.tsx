import { useState } from "react";
import {
  parseInvoice,
  validateInvoice,
  type EdiFormat,
  type ParseResponse,
  type ValidateResponse,
} from "../api";

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      resolve(result.split(",")[1] ?? "");
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

export function InspectTab() {
  const [format, setFormat] = useState<EdiFormat>("edifact");
  const [content, setContent] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [parseResult, setParseResult] = useState<ParseResponse | null>(null);
  const [validateResult, setValidateResult] = useState<ValidateResponse | null>(null);

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    if (format === "zugferd") {
      setContent(await fileToBase64(file));
    } else {
      setContent(await file.text());
    }
  }

  async function handleAnalyze() {
    if (!content.trim()) {
      setError("paste or upload some content first");
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

  return (
    <div className="panel">
      <p className="panel-description">
        Paste or upload an EDI/e-invoicing message to see it explained segment-by-segment and
        validated against real spec rules — the verdict is always deterministic, never a model's
        guess.
      </p>

      <div className="form-row">
        <label>
          Format
          <select value={format} onChange={(e) => setFormat(e.target.value as EdiFormat)}>
            <option value="edifact">EDIFACT INVOIC</option>
            <option value="ubl">UBL Invoice</option>
            <option value="cii">CII (raw XML)</option>
            <option value="zugferd">ZUGFeRD / Factur-X (PDF)</option>
          </select>
        </label>
        <label>
          Upload file
          <input type="file" onChange={handleFileChange} />
        </label>
        <button onClick={handleAnalyze} disabled={loading}>
          {loading ? "Analyzing…" : "Analyze"}
        </button>
      </div>

      {format !== "zugferd" ? (
        <textarea
          className="content-input"
          placeholder="Paste EDIFACT / UBL / CII content here…"
          value={content}
          onChange={(e) => {
            setContent(e.target.value);
            setFileName(null);
          }}
          rows={8}
        />
      ) : (
        fileName && <p className="hint">Loaded: {fileName} (base64-encoded, {content.length} chars)</p>
      )}

      {error && <div className="error-box">{error}</div>}

      {validateResult && (
        <div className="result-box">
          <div className="result-header">
            <span className={`badge badge-${validateResult.verdict ?? "error"}`}>
              {validateResult.verdict ?? validateResult.error ?? "error"}
            </span>
          </div>
          {validateResult.findings && (
            <ul className="findings-list">
              {validateResult.findings.map((f, i) => (
                <li key={i} className={`finding finding-${f.level}`}>
                  <span className="finding-code">{f.code}</span> {f.message}
                </li>
              ))}
            </ul>
          )}
          {validateResult.citations && validateResult.citations.length > 0 && (
            <>
              <h4>Citations</h4>
              <ul className="citations-list">
                {validateResult.citations.map((c, i) => (
                  <li key={i}>
                    <code>{c.doc_id}</code> § {c.section} ({Math.round(c.score * 100)}%)
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {parseResult && (
        <div className="result-box">
          <h4>Segment breakdown</h4>
          {parseResult.segments && (
            <table className="segments-table">
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
            <table className="segments-table">
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
      )}
    </div>
  );
}
