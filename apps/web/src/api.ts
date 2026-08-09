const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8788";

export type EdiFormat = "edifact" | "ubl" | "cii" | "zugferd";

export interface GenerateResponse {
  format: EdiFormat;
  content: string;
  encoding?: "base64";
  cii_xml?: string;
}

export interface ParseResponse {
  format: EdiFormat;
  segments?: { tag: string; description: string; elements: string[][] }[];
  elements?: { path: string; text: string }[];
  error?: string;
}

export interface Citation {
  doc_id: string;
  section: string;
  sha256: string;
  score: number;
}

export interface ValidateResponse {
  format: EdiFormat;
  verdict?: "valid" | "invalid";
  findings?: { level: string; code: string; message: string }[];
  citations?: Citation[];
  error?: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${path} failed (${res.status}): ${detail}`);
  }
  return res.json() as Promise<T>;
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request(path, { method: "POST", body: JSON.stringify(body) });
}

export function generateInvoice(params: {
  format: EdiFormat;
  numLines: number;
  seed?: number;
}): Promise<GenerateResponse> {
  return postJson("/api/generate", params);
}

export function parseInvoice(params: { content: string; format: EdiFormat }): Promise<ParseResponse> {
  return postJson("/api/parse", params);
}

export function validateInvoice(params: { content: string; format: EdiFormat }): Promise<ValidateResponse> {
  return postJson("/api/validate", params);
}

// --- Mapping tool ---

export interface SourceField {
  segmentIndex: number;
  elementIndex: number;
  componentIndex: number;
  label: string;
  value: string;
}

export interface SourceRef {
  segment_index: number;
  element_index: number;
  component_index: number;
}

export interface FieldMapping {
  target_field: string;
  source: SourceRef;
}

export interface TargetFieldDef {
  field: string;
  label: string;
}

export interface LineSubfieldDef {
  subfield: string;
  label: string;
}

export interface MappingProfile {
  id: number;
  name: string;
  fromFormat: "edifact";
  toFormat: "ubl";
  fieldMappings: FieldMapping[];
  createdAt: string;
  updatedAt: string;
}

export interface ApplyMappingResult {
  ubl_xml?: string;
  notes?: string[];
  validation?: { level: string; code: string; message: string }[];
  error?: string;
}

export function fetchSourceFields(content: string): Promise<{ fields: SourceField[] }> {
  return postJson("/api/mapping-fields/source", { content, format: "edifact" });
}

export function fetchTargetFields(): Promise<{ header: TargetFieldDef[]; lineSubfields: LineSubfieldDef[] }> {
  return request("/api/mapping-fields/target?format=ubl");
}

export function listMappingProfiles(): Promise<MappingProfile[]> {
  return request("/api/mapping-profiles");
}

export function createMappingProfile(params: {
  name: string;
  fromFormat: "edifact";
  toFormat: "ubl";
  fieldMappings: FieldMapping[];
}): Promise<MappingProfile> {
  return postJson("/api/mapping-profiles", params);
}

export function deleteMappingProfile(id: number): Promise<{ deleted: number }> {
  return request(`/api/mapping-profiles/${id}`, { method: "DELETE" });
}

export function applyMappingProfile(id: number, content: string): Promise<ApplyMappingResult> {
  return postJson(`/api/mapping-profiles/${id}/apply`, { content });
}
