import type { FastifyInstance } from "fastify";
import { z } from "zod";

import { db } from "../db/client.js";
import { toolInvocations } from "../db/schema.js";
import { callMcpTool } from "../mcp/client.js";

const bodySchema = z.object({
  content: z.string().min(1),
  format: z.enum(["edifact", "ubl", "cii", "zugferd"]),
});

export function registerParseRoute(app: FastifyInstance) {
  app.post("/api/parse", async (request, reply) => {
    const parsed = bodySchema.safeParse(request.body);
    if (!parsed.success) {
      return reply.status(400).send({ error: parsed.error.flatten() });
    }
    const { content, format } = parsed.data;

    const result = await callMcpTool<Record<string, unknown>>("parse_edi", { content, format });

    // Metadata only — never the submitted content itself (docs/threat-model.md I1).
    const itemCount =
      (result.segments as unknown[] | undefined)?.length ??
      (result.elements as unknown[] | undefined)?.length ??
      0;
    await db.insert(toolInvocations).values({
      tool: "parse_edi",
      format,
      summary: result.error ? `parse failed: ${result.error}` : `parsed ${itemCount} items`,
    });

    return result;
  });
}
