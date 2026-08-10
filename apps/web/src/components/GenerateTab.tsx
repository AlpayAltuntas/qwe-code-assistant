import { Download, FileOutput, Sparkles } from "lucide-react";
import { useState } from "react";
import { generateInvoice, type EdiFormat, type GenerateResponse } from "../api";
import { Alert, Badge, Button, CodeBlock, EmptyState, SelectField, TextField } from "./ui";

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

const FORMAT_OPTIONS = [
  { value: "edifact", label: "EDIFACT INVOIC" },
  { value: "ubl", label: "UBL Invoice" },
  { value: "cii", label: "CII (raw XML)" },
  { value: "zugferd", label: "ZUGFeRD / Factur-X (PDF/A-3)" },
];

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
    <div>
      <div className="form-row">
        <SelectField
          label="Format"
          value={format}
          onChange={(e) => setFormat(e.target.value as EdiFormat)}
          options={FORMAT_OPTIONS}
        />
        <TextField
          label="Line items"
          type="number"
          min={1}
          max={20}
          value={numLines}
          onChange={(e) => setNumLines(Number(e.target.value))}
          style={{ width: 90 }}
        />
        <TextField
          label="Seed"
          type="text"
          placeholder="random if empty"
          value={seed}
          onChange={(e) => setSeed(e.target.value)}
          style={{ width: 140 }}
        />
      </div>
      <div className="form-actions">
        <Button variant="primary" icon={<Sparkles size={15} />} loading={loading} onClick={handleGenerate}>
          Generate invoice
        </Button>
      </div>

      {error && (
        <div style={{ marginTop: 20 }}>
          <Alert variant="danger">{error}</Alert>
        </div>
      )}

      <div className="section-heading">Result</div>

      {!result && !loading && !error && (
        <EmptyState
          icon={<FileOutput size={28} strokeWidth={1.5} />}
          title="Nothing generated yet"
          description="Pick a format and click Generate to create a fictional test invoice — never derived from real customer data."
        />
      )}

      {result && (
        <>
          <div className="result-header">
            <div className="result-header-left">
              <Badge variant="info">{result.format}</Badge>
              <span className="hint" style={{ margin: 0 }}>
                {numLines} line item{numLines === 1 ? "" : "s"}
              </span>
            </div>
            <Button size="sm" icon={<Download size={14} />} onClick={handleDownload}>
              Download
            </Button>
          </div>

          {result.encoding === "base64" ? (
            <>
              <p className="hint">
                Base64-encoded PDF/A-3 (~{Math.round((result.content.length * 3) / 4)} bytes). The visual
                layer is a blank placeholder page — the embedded CII XML below is the authoritative
                content.
              </p>
              {result.cii_xml && <CodeBlock content={result.cii_xml} label="Embedded CII XML" />}
            </>
          ) : (
            <CodeBlock content={result.content} label={result.format} />
          )}
        </>
      )}
    </div>
  );
}
