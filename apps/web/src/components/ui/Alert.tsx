import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import type { ReactNode } from "react";

type Variant = "danger" | "warning" | "info" | "success";

const ICONS: Record<Variant, ReactNode> = {
  danger: <XCircle size={16} />,
  warning: <AlertTriangle size={16} />,
  info: <Info size={16} />,
  success: <CheckCircle2 size={16} />,
};

interface AlertProps {
  variant?: Variant;
  children: ReactNode;
}

export function Alert({ variant = "info", children }: AlertProps) {
  return (
    <div className={`alert alert-${variant}`} role={variant === "danger" ? "alert" : undefined}>
      <span className="alert-icon">{ICONS[variant]}</span>
      <span>{children}</span>
    </div>
  );
}
