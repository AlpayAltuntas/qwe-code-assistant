import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import type { ReactNode } from "react";

type Variant = "neutral" | "success" | "danger" | "warning" | "info";

const ICONS: Record<Variant, ReactNode> = {
  neutral: null,
  success: <CheckCircle2 size={13} />,
  danger: <XCircle size={13} />,
  warning: <AlertTriangle size={13} />,
  info: <Info size={13} />,
};

interface BadgeProps {
  variant?: Variant;
  icon?: boolean;
  children: ReactNode;
}

export function Badge({ variant = "neutral", icon = false, children }: BadgeProps) {
  return (
    <span className={`badge badge-${variant}`}>
      {icon && ICONS[variant]}
      {children}
    </span>
  );
}
