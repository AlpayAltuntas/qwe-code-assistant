import type { FastifyInstance } from "fastify";
import { z } from "zod";

import { db } from "../db/client.js";
import { toolInvocations } from "../db/schema.js";
import { callMcpTool } from "../mcp/client.js";

const TARGET_FORMATS = ["edifact", "ubl", "cii", "zugferd"] as const;

const buildSchema = z.object({
  header: z.record(z.string(), z.string()),
  lines: z.array(z.record(z.string(), z.string())),
  toFormat: z.enum(TARGET_FORMATS),
});

interface BuildDocumentResult {
  format?: string;
  content?: string;
  encoding?: "base64";
  cii_xml?: string;
  notes?: string[];
  validation?: { level: string; code: string; message: string }[];
  error?: string;
}

export function registerDocumentsRoute(app: FastifyInstance) {
  app.post("/api/documents", async (request, reply) => {
    const parsed = buildSchema.safeParse(request.body);
    if (!parsed.success) return reply.status(400).send({ error: parsed.error.flatten() });

    const { header, lines, toFormat } = parsed.data;

    const result = await callMcpTool<BuildDocumentResult>("build_document", {
      header,
      lines,
      to_format: toFormat,
    });

    await db.insert(toolInvocations).values({
      tool: "build_document",
      format: toFormat,
      summary: result.error ? `document build failed: ${result.error}` : `built a ${toFormat} document`,
    });

    return result;
  });
}
