import cors from "@fastify/cors";
import Fastify from "fastify";

import { config } from "./config.js";
import { registerGenerateRoute } from "./routes/generate.js";
import { registerMappingFieldsRoute } from "./routes/mappingFields.js";
import { registerMappingProfilesRoutes } from "./routes/mappingProfiles.js";
import { registerParseRoute } from "./routes/parse.js";
import { registerValidateRoute } from "./routes/validate.js";

const app = Fastify({ logger: true });

// No wildcard — see docs/threat-model.md S3 (localhost drive-by / CSRF
// from another tab). Only the Vite dev server's own origin is allowed.
await app.register(cors, { origin: [config.corsOrigin] });

app.get("/health", async () => ({ status: "ok" }));

registerGenerateRoute(app);
registerParseRoute(app);
registerValidateRoute(app);
registerMappingFieldsRoute(app);
registerMappingProfilesRoutes(app);

try {
  await app.listen({ host: config.host, port: config.port });
} catch (err) {
  app.log.error(err);
  process.exit(1);
}
