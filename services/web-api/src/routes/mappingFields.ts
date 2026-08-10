import type { FastifyInstance } from "fastify";
import { z } from "zod";

import { callMcpTool } from "../mcp/client.js";

const MAPPING_SOURCE_FORMATS = ["edifact", "ubl", "cii", "zugferd"] as const;

const sourceBodySchema = z.object({
  content: z.string().min(1),
  format: z.enum(MAPPING_SOURCE_FORMATS),
});

// One address shape for every source format — {parent_tag, tag,
// occurrence} — see services/mcp-server/src/mcp_server/ir.py.
interface SourceFieldRef {
  parent_tag: string;
  tag: string;
  occurrence: number;
  label: string;
  value: string;
}

interface DescribeSourceFieldsResult {
  header?: SourceFieldRef[];
  line_template?: SourceFieldRef[];
  line_count?: number;
  error?: string;
}

// Canonical target field vocabulary, shared across all target formats
// (mirrors services/mcp-server/src/mcp_server/mapping.py
// HEADER_TARGET_FIELDS/LINE_SUBFIELDS). Not every target format has a
// home for every field — e.g. this EDIFACT builder has no address
// fields — the apply step reports what got dropped in its `notes`
// rather than this catalog trying to filter per target format up front.
// `group` is UI-only, for organizing the field list into sections.
export const CANONICAL_HEADER_TARGET_FIELDS = [
  { field: "invoice_id", label: "Invoice ID", group: "Invoice" },
  { field: "issue_date", label: "Issue date", group: "Invoice" },
  { field: "due_date", label: "Due date", group: "Invoice" },
  { field: "invoice_type_code", label: "Invoice type code", group: "Invoice" },
  { field: "currency", label: "Currency", group: "Invoice" },
  { field: "buyer_reference", label: "Buyer reference", group: "Invoice" },
  { field: "order_reference", label: "Order reference", group: "Invoice" },
  { field: "contract_reference", label: "Contract reference", group: "Invoice" },

  { field: "supplier_name", label: "Name", group: "Supplier" },
  { field: "supplier_street", label: "Street", group: "Supplier" },
  { field: "supplier_city", label: "City", group: "Supplier" },
  { field: "supplier_postal_zone", label: "Postal code", group: "Supplier" },
  { field: "supplier_country_code", label: "Country code", group: "Supplier" },
  { field: "supplier_tax_id", label: "Tax / VAT ID", group: "Supplier" },
  { field: "supplier_email", label: "Email", group: "Supplier" },

  { field: "customer_name", label: "Name", group: "Customer" },
  { field: "customer_street", label: "Street", group: "Customer" },
  { field: "customer_city", label: "City", group: "Customer" },
  { field: "customer_postal_zone", label: "Postal code", group: "Customer" },
  { field: "customer_country_code", label: "Country code", group: "Customer" },
  { field: "customer_tax_id", label: "Tax / VAT ID", group: "Customer" },
  { field: "customer_email", label: "Email", group: "Customer" },

  { field: "payment_means_code", label: "Payment means code", group: "Payment" },
  { field: "payment_id", label: "Payment reference", group: "Payment" },
  { field: "payment_terms_note", label: "Payment terms", group: "Payment" },

  { field: "tax_exclusive_amount", label: "Tax-exclusive amount", group: "Totals & tax" },
  { field: "tax_inclusive_amount", label: "Tax-inclusive amount", group: "Totals & tax" },
  { field: "tax_total_amount", label: "Tax total amount", group: "Totals & tax" },
  { field: "tax_category_id", label: "Tax category", group: "Totals & tax" },
  { field: "tax_percent", label: "Tax percent", group: "Totals & tax" },
  { field: "payable_amount", label: "Payable amount", group: "Totals & tax" },
] as const;

export const CANONICAL_LINE_SUBFIELDS = [
  { subfield: "item_name", label: "Item name" },
  { subfield: "item_description", label: "Item description" },
  { subfield: "buyers_item_id", label: "Buyer's item ID" },
  { subfield: "sellers_item_id", label: "Seller's item ID" },
  { subfield: "quantity", label: "Quantity" },
  { subfield: "unit_code", label: "Unit code" },
  { subfield: "price_amount", label: "Unit price" },
  { subfield: "line_extension_amount", label: "Line amount" },
  { subfield: "tax_category_id", label: "Tax category" },
  { subfield: "tax_percent", label: "Tax percent" },
] as const;

export function registerMappingFieldsRoute(app: FastifyInstance) {
  app.post("/api/mapping-fields/source", async (request, reply) => {
    const parsed = sourceBodySchema.safeParse(request.body);
    if (!parsed.success) {
      return reply.status(400).send({ error: parsed.error.flatten() });
    }
    const { content, format } = parsed.data;

    const result = await callMcpTool<DescribeSourceFieldsResult>("describe_mapping_source_fields", {
      content,
      format,
    });
    if (result.error || !result.header) {
      return reply.status(422).send({ error: result.error ?? "could not parse content" });
    }

    return {
      header: result.header,
      lineTemplate: result.line_template ?? [],
      lineCount: result.line_count ?? 0,
    };
  });

  app.get("/api/mapping-fields/target", async () => {
    return { header: CANONICAL_HEADER_TARGET_FIELDS, lineSubfields: CANONICAL_LINE_SUBFIELDS };
  });
}
