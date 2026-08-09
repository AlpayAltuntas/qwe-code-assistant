import type { FastifyInstance } from "fastify";
import { z } from "zod";

import { db } from "../db/client.js";
import { toolInvocations } from "../db/schema.js";
import { callMcpTool } from "../mcp/client.js";

const bodySchema = z.object({
  content: z.string().min(1),
  format: z.enum(["edifact", "ubl", "cii", "zugferd"]),
});

interface ValidateResult {
  format: string;
  verdict?: "valid" | "invalid";
  findings?: { level: string; code: string; message: string }[];
  citations?: unknown[];
  error?: string;
}

export function registerValidateRoute(app: FastifyInstance) {
  app.post("/api/validate", async (request, reply) => {
    const parsed = bodySchema.safeParse(request.body);
    if (!parsed.success) {
      return reply.status(400).send({ error: parsed.error.flatten() });
    }
    const { content, format } = parsed.data;

    const result = await callMcpTool<ValidateResult>("validate_with_citation", { content, format });

    // Metadata only — never the submitted content itself (docs/threat-model.md I1).
    await db.insert(toolInvocations).values({
      tool: "validate_with_citation",
      format,
      verdict: result.verdict ?? null,
      summary: result.error
        ? `validation failed: ${result.error}`
        : `${result.findings?.length ?? 0} finding(s), ${result.citations?.length ?? 0} citation(s)`,
    });

    return result;
  });
}
