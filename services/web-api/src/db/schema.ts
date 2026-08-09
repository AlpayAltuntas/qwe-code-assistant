import { jsonb, pgTable, serial, text, timestamp } from "drizzle-orm/pg-core";

// Metadata/audit only — never raw invoice content or payload text.
// See docs/threat-model.md I1 (no PII at rest) and R3 (this table's DB
// role gets INSERT+SELECT only, no UPDATE/DELETE — see db/grants.sql).
export const toolInvocations = pgTable("tool_invocations", {
  id: serial("id").primaryKey(),
  tool: text("tool").notNull(), // 'generate_synthetic_invoice' | 'parse_edi' | 'validate_with_citation'
  format: text("format").notNull(), // 'edifact' | 'ubl' | 'cii' | 'zugferd'
  verdict: text("verdict"), // only set for validate_with_citation
  summary: text("summary").notNull(), // short human-readable outcome, no payload content
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

// User-authored field-correspondence configuration, not audit history —
// this table is genuinely mutable (rename/edit/delete a saved mapping),
// so it gets a full-CRUD grant, deliberately different from
// tool_invocations' insert-only one. Still no invoice content: field_mappings
// stores positional coordinates into a sample document's parsed segments
// (segment/element/component index), not the sample's actual values.
export const mappingProfiles = pgTable("mapping_profiles", {
  id: serial("id").primaryKey(),
  name: text("name").notNull(),
  fromFormat: text("from_format").notNull(), // 'edifact'
  toFormat: text("to_format").notNull(), // 'ubl'
  fieldMappings: jsonb("field_mappings").notNull(), // { targetField, source: {segmentIndex, elementIndex, componentIndex} }[]
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});
