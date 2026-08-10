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
//
// Any of EDIFACT/UBL/CII/ZUGFeRD can be a mapping's source or target.
// Source fields are addressed by tag/position + occurrence-of-that-shape
// (not raw document position), so a mapping built from these addresses
// keeps working on documents where line counts (or other counts) differ
// — see mapping.py's module docstring for why. EDIFACT source fields
// carry {tag, occurrence, element_index, component_index}; UBL/CII (XML)
// source fields carry {parent_tag, tag, occurrence} instead — see
// xmlmap.py. Line-item fields are a *template*: one relative address,
// applied to every line-item group actually found on whatever document
// the mapping gets applied to (so 3 mapped line subfields work whether
// the target document has 1 line or 30).

export type MappingFormat = "edifact" | "ubl" | "cii" | "zugferd";

// One address shape for every source format — see
// services/mcp-server/src/mcp_server/ir.py. For EDIFACT, parent_tag is
// the segment tag and tag is a synthesized "e<i>.c<j>" position label;
// for UBL/CII, both are real XML element names.
export interface SourceField {
  parent_tag: string;
  tag: string;
  occurrence: number;
  label: string;
  value: string;
}

export type FieldRef = {
  parent_tag: string;
  tag: string;
  occurrence: number;
};

export type FieldSource = { kind: "field"; ref: FieldRef } | { kind: "constant"; value: string };

export interface FieldMapping {
  target_field: string;
  source: FieldSource;
}

export interface TargetFieldDef {
  field: string;
  label: string;
  group: string;
}

export interface LineSubfieldDef {
  subfield: string;
  label: string;
}

export interface MappingProfile {
  id: number;
  name: string;
  fromFormat: MappingFormat;
  toFormat: MappingFormat;
  fieldMappings: FieldMapping[];
  createdAt: string;
  updatedAt: string;
}

export interface ApplyMappingResult {
  format?: MappingFormat;
  content?: string;
  encoding?: "base64";
  cii_xml?: string;
  notes?: string[];
  validation?: { level: string; code: string; message: string }[];
  error?: string;
}

export function fetchSourceFields(
  content: string,
  format: MappingFormat,
): Promise<{ header: SourceField[]; lineTemplate: SourceField[]; lineCount: number }> {
  return postJson("/api/mapping-fields/source", { content, format });
}

export function fetchTargetFields(): Promise<{ header: TargetFieldDef[]; lineSubfields: LineSubfieldDef[] }> {
  return request("/api/mapping-fields/target");
}

export function listMappingProfiles(): Promise<MappingProfile[]> {
  return request("/api/mapping-profiles");
}

export function createMappingProfile(params: {
  name: string;
  fromFormat: MappingFormat;
  toFormat: MappingFormat;
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

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE_URL}/health`);
    return res.ok;
  } catch {
    return false;
  }
}
