import { ChevronDown } from "lucide-react";
import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

interface FieldWrapperProps {
  label?: string;
  hint?: string;
  children: ReactNode;
}

function FieldWrapper({ label, hint, children }: FieldWrapperProps) {
  return (
    <label className="field">
      {label && <span className="field-label">{label}</span>}
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  hint?: string;
}

export function TextField({ label, hint, className = "", ...rest }: TextFieldProps) {
  return (
    <FieldWrapper label={label} hint={hint}>
      <input className={`input ${className}`} {...rest} />
    </FieldWrapper>
  );
}

interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  hint?: string;
  monospace?: boolean;
}

export function TextArea({ label, hint, monospace = true, className = "", ...rest }: TextAreaProps) {
  return (
    <FieldWrapper label={label} hint={hint}>
      <textarea className={`textarea ${monospace ? "textarea-mono" : ""} ${className}`} {...rest} />
    </FieldWrapper>
  );
}

interface SelectFieldProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  hint?: string;
  options: { value: string; label: string }[];
  placeholder?: string;
}

export function SelectField({ label, hint, options, placeholder, className = "", ...rest }: SelectFieldProps) {
  return (
    <FieldWrapper label={label} hint={hint}>
      <div className="select-wrap">
        <select className={`select ${className}`} {...rest}>
          {placeholder && <option value="">{placeholder}</option>}
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <ChevronDown size={14} />
      </div>
    </FieldWrapper>
  );
}
