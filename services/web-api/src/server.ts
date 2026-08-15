import cors from "@fastify/cors";
import Fastify from "fastify";

import { config } from "./config.js";
import { registerDocumentsRoute } from "./routes/documents.js";
import { registerGenerateRoute } from "./routes/generate.js";
import { registerMappingFieldsRoute } from "./routes/mappingFields.js";
import { registerMappingProfilesRoutes } from "./routes/mappingProfiles.js";
import { registerParseRoute } from "./routes/parse.js";
import { registerValidateRoute } from "./routes/validate.js";

const app = Fastify({ logger: true });

// No wildcard — see docs/threat-model.md S3 (localhost drive-by / CSRF
// from another tab). Only the Vite dev server's own origin is allowed —
// but browsers treat "localhost" and "127.0.0.1" as different origins
// even though they're the same loopback machine, so both spellings of
// CORS_ORIGIN's host are allowed (whichever one the user actually types
// into the address bar), never a wildcard.
// @fastify/cors defaults `methods` to "GET,HEAD,POST" — DELETE (mapping
// profile deletion) and PUT (renaming/updating one) need to be listed
// explicitly or the preflight silently rejects them.
const corsOriginAlt = config.corsOrigin.includes("127.0.0.1")
  ? config.corsOrigin.replace("127.0.0.1", "localhost")
  : config.corsOrigin.includes("localhost")
    ? config.corsOrigin.replace("localhost", "127.0.0.1")
    : null;
const allowedOrigins = corsOriginAlt ? [config.corsOrigin, corsOriginAlt] : [config.corsOrigin];
await app.register(cors, { origin: allowedOrigins, methods: ["GET", "HEAD", "POST", "PUT", "DELETE"] });

app.get("/health", async () => ({ status: "ok" }));

registerGenerateRoute(app);
registerParseRoute(app);
registerValidateRoute(app);
registerMappingFieldsRoute(app);
registerMappingProfilesRoutes(app);
registerDocumentsRoute(app);

try {
  await app.listen({ host: config.host, port: config.port });
} catch (err) {
  app.log.error(err);
  process.exit(1);
}
