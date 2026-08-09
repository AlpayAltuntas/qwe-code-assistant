import { useState } from "react";
import { generateInvoice, type EdiFormat, type GenerateResponse } from "../api";

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

const FORMAT_EXT: Record<EdiFormat, string> = {
  edifact: "edi",
  ubl: "xml",
  cii: "xml",
  zugferd: "pdf",
};

export function GenerateTab() {
  const [format, setFormat] = useState<EdiFormat>("edifact");
  const [numLines, setNumLines] = useState(2);
  const [seed, setSeed] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<GenerateResponse | null>(null);

  async function handleGenerate() {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await generateInvoice({
        format,
        numLines,
        seed: seed.trim() ? Number(seed) : undefined,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  function handleDownload() {
    if (!result) return;
    const filename = `synthetic-invoice.${FORMAT_EXT[result.format]}`;
    if (result.encoding === "base64") {
      downloadBlob(filename, result.content, "application/pdf", true);
    } else {
      downloadBlob(filename, result.content, "text/plain");
    }
  }

  return (
    <div className="panel">
      <p className="panel-description">
        Generate a synthetic, entirely fictional test invoice — never derived from real customer
        data. Useful as a fixture for your own test suite.
      </p>

      <div className="form-row">
        <label>
          Format
          <select value={format} onChange={(e) => setFormat(e.target.value as EdiFormat)}>
            <option value="edifact">EDIFACT INVOIC</option>
            <option value="ubl">UBL Invoice</option>
            <option value="cii">CII (raw XML)</option>
            <option value="zugferd">ZUGFeRD / Factur-X (PDF/A-3)</option>
          </select>
        </label>
        <label>
          Line items
          <input
            type="number"
            min={1}
            max={20}
            value={numLines}
            onChange={(e) => setNumLines(Number(e.target.value))}
          />
        </label>
        <label>
          Seed (optional)
          <input
            type="text"
            placeholder="reproducible if set"
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
          />
        </label>
        <button onClick={handleGenerate} disabled={loading}>
          {loading ? "Generating…" : "Generate"}
        </button>
      </div>

      {error && <div className="error-box">{error}</div>}

      {result && (
        <div className="result-box">
          <div className="result-header">
            <span className="badge">{result.format}</span>
            <button onClick={handleDownload}>Download</button>
          </div>
          {result.encoding === "base64" ? (
            <>
              <p className="hint">
                Base64-encoded PDF/A-3 ({Math.round((result.content.length * 3) / 4)} bytes). The
                visual layer is a blank placeholder page — the embedded CII XML below is the
                authoritative content.
              </p>
              {result.cii_xml && <pre className="content-block">{result.cii_xml}</pre>}
            </>
          ) : (
            <pre className="content-block">{result.content}</pre>
          )}
        </div>
      )}
    </div>
  );
}
