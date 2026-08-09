import type { FastifyInstance } from "fastify";
import { z } from "zod";

import { callMcpTool } from "../mcp/client.js";

const sourceBodySchema = z.object({
  content: z.string().min(1),
  format: z.literal("edifact"),
});

interface ParsedSegment {
  tag: string;
  description: string;
  elements: string[][];
}

// Header fields map 1:1 onto InvoiceFields attributes on the Python side
// (see services/mcp-server/src/mcp_server/mapping.py HEADER_TARGET_FIELDS).
export const UBL_HEADER_TARGET_FIELDS = [
  { field: "invoice_id", label: "Invoice ID (cbc:ID)" },
  { field: "issue_date", label: "Issue date (cbc:IssueDate)" },
  { field: "invoice_type_code", label: "Invoice type code (cbc:InvoiceTypeCode)" },
  { field: "currency", label: "Currency (cbc:DocumentCurrencyCode)" },
  { field: "supplier_name", label: "Supplier name (AccountingSupplierParty)" },
  { field: "customer_name", label: "Customer name (AccountingCustomerParty)" },
  { field: "payable_amount", label: "Payable amount (LegalMonetaryTotal)" },
];

export const UBL_LINE_SUBFIELDS = [
  { subfield: "item_name", label: "Item name" },
  { subfield: "quantity", label: "Quantity" },
  { subfield: "unit_code", label: "Unit code" },
  { subfield: "line_extension_amount", label: "Line amount" },
  { subfield: "price_amount", label: "Unit price" },
];

export function registerMappingFieldsRoute(app: FastifyInstance) {
  app.post("/api/mapping-fields/source", async (request, reply) => {
    const parsed = sourceBodySchema.safeParse(request.body);
    if (!parsed.success) {
      return reply.status(400).send({ error: parsed.error.flatten() });
    }
    const { content, format } = parsed.data;

    const result = await callMcpTool<{ segments?: ParsedSegment[]; error?: string }>("parse_edi", {
      content,
      format,
    });
    if (result.error || !result.segments) {
      return reply.status(422).send({ error: result.error ?? "could not parse content" });
    }

    // Flatten into addressable (segment_index, element_index, component_index)
    // coordinates with a human-readable label, for the mapping UI's dropdowns.
    const fields = result.segments.flatMap((seg, segmentIndex) =>
      seg.elements.flatMap((element, elementIndex) =>
        element.map((value, componentIndex) => ({
          segmentIndex,
          elementIndex,
          componentIndex,
          label: `${seg.tag}[${elementIndex}][${componentIndex}] = ${value || "(empty)"}`,
          value,
        })),
      ),
    );

    return { fields };
  });

  app.get("/api/mapping-fields/target", async (request, reply) => {
    const format = (request.query as { format?: string }).format;
    if (format !== "ubl") {
      return reply.status(400).send({ error: "only format=ubl is supported" });
    }
    return { header: UBL_HEADER_TARGET_FIELDS, lineSubfields: UBL_LINE_SUBFIELDS };
  });
}
