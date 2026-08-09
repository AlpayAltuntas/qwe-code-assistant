import { eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { z } from "zod";

import { db } from "../db/client.js";
import { mappingProfiles, toolInvocations } from "../db/schema.js";
import { callMcpTool } from "../mcp/client.js";

const fieldMappingSchema = z.object({
  target_field: z.string().min(1),
  source: z.object({
    segment_index: z.number().int(),
    element_index: z.number().int(),
    component_index: z.number().int(),
  }),
});

const createSchema = z.object({
  name: z.string().min(1),
  fromFormat: z.literal("edifact"),
  toFormat: z.literal("ubl"),
  fieldMappings: z.array(fieldMappingSchema),
});

const updateSchema = z.object({
  name: z.string().min(1).optional(),
  fieldMappings: z.array(fieldMappingSchema).optional(),
});

const applySchema = z.object({
  content: z.string().min(1),
});

export function registerMappingProfilesRoutes(app: FastifyInstance) {
  app.get("/api/mapping-profiles", async () => {
    return db.select().from(mappingProfiles).orderBy(mappingProfiles.updatedAt);
  });

  app.get("/api/mapping-profiles/:id", async (request, reply) => {
    const id = Number((request.params as { id: string }).id);
    const [profile] = await db.select().from(mappingProfiles).where(eq(mappingProfiles.id, id));
    if (!profile) return reply.status(404).send({ error: "not found" });
    return profile;
  });

  app.post("/api/mapping-profiles", async (request, reply) => {
    const parsed = createSchema.safeParse(request.body);
    if (!parsed.success) return reply.status(400).send({ error: parsed.error.flatten() });

    const [created] = await db
      .insert(mappingProfiles)
      .values({
        name: parsed.data.name,
        fromFormat: parsed.data.fromFormat,
        toFormat: parsed.data.toFormat,
        fieldMappings: parsed.data.fieldMappings,
      })
      .returning();
    return reply.status(201).send(created);
  });

  app.put("/api/mapping-profiles/:id", async (request, reply) => {
    const id = Number((request.params as { id: string }).id);
    const parsed = updateSchema.safeParse(request.body);
    if (!parsed.success) return reply.status(400).send({ error: parsed.error.flatten() });

    const [updated] = await db
      .update(mappingProfiles)
      .set({ ...parsed.data, updatedAt: new Date() })
      .where(eq(mappingProfiles.id, id))
      .returning();
    if (!updated) return reply.status(404).send({ error: "not found" });
    return updated;
  });

  app.delete("/api/mapping-profiles/:id", async (request, reply) => {
    const id = Number((request.params as { id: string }).id);
    const deleted = await db.delete(mappingProfiles).where(eq(mappingProfiles.id, id)).returning();
    if (deleted.length === 0) return reply.status(404).send({ error: "not found" });
    return { deleted: id };
  });

  app.post("/api/mapping-profiles/:id/apply", async (request, reply) => {
    const id = Number((request.params as { id: string }).id);
    const parsed = applySchema.safeParse(request.body);
    if (!parsed.success) return reply.status(400).send({ error: parsed.error.flatten() });

    const [profile] = await db.select().from(mappingProfiles).where(eq(mappingProfiles.id, id));
    if (!profile) return reply.status(404).send({ error: "not found" });

    const result = await callMcpTool<{ ubl_xml?: string; notes?: string[]; error?: string }>(
      "apply_mapping_profile",
      {
        content: parsed.data.content,
        field_mappings: profile.fieldMappings,
        from_format: profile.fromFormat,
        to_format: profile.toFormat,
      },
    );

    await db.insert(toolInvocations).values({
      tool: "apply_mapping_profile",
      format: profile.toFormat,
      summary: result.error
        ? `mapping "${profile.name}" failed: ${result.error}`
        : `applied mapping "${profile.name}"`,
    });

    return result;
  });
}
