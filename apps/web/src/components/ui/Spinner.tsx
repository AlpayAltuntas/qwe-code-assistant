import { Loader2 } from "lucide-react";

export function Spinner({ size = 20, label }: { size?: number; label?: string }) {
  return (
    <div className="spinner-row">
      <Loader2 size={size} className="btn-spin" />
      {label && <span className="muted">{label}</span>}
    </div>
  );
}
