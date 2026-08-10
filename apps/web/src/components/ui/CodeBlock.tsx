import { Check, Copy } from "lucide-react";
import { useState } from "react";

interface CodeBlockProps {
  content: string;
  label?: string;
  maxHeight?: number;
}

export function CodeBlock({ content, label, maxHeight }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  }

  return (
    <div className="code-block">
      <div className="code-block-toolbar">
        {label && <span className="code-block-label">{label}</span>}
        <button className="code-block-copy" onClick={handleCopy} type="button">
          {copied ? <Check size={13} /> : <Copy size={13} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="code-block-content" style={maxHeight ? { maxHeight } : undefined}>
        {content}
      </pre>
    </div>
  );
}
