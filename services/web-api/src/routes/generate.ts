import type { FastifyInstance } from "fastify";
import { z } from "zod";

import { db } from "../db/client.js";
import { toolInvocations } from "../db/schema.js";
import { callMcpTool } from "../mcp/client.js";

const bodySchema = z.object({
  format: z.enum(["edifact", "ubl", "cii", "zugferd"]),
  numLines: z.number().int().min(1).max(20).default(2),
  seed: z.number().int().optional(),
});

interface GenerateResult {
  format: string;
  content: string;
  encoding?: string;
  cii_xml?: string;
}

export function registerGenerateRoute(app: FastifyInstance) {
  app.post("/api/generate", async (request, reply) => {
    const parsed = bodySchema.safeParse(request.body);
    if (!parsed.success) {
      return reply.status(400).send({ error: parsed.error.flatten() });
    }
    const { format, numLines, seed } = parsed.data;

    const result = await callMcpTool<GenerateResult>("generate_synthetic_invoice", {
      format,
      num_lines: numLines,
      seed,
    });

    await db.insert(toolInvocations).values({
      tool: "generate_synthetic_invoice",
      format,
      summary: `generated a ${numLines}-line synthetic ${format} invoice`,
    });

    return result;
  });
}
