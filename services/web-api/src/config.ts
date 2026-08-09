import "dotenv/config";

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`missing required env var: ${name}`);
  return value;
}

export const config = {
  databaseUrl: required("DATABASE_URL"),
  host: process.env.HOST ?? "127.0.0.1",
  port: Number(process.env.PORT ?? 8788),
  mcpServerDir: required("MCP_SERVER_DIR"),
  corsOrigin: process.env.CORS_ORIGIN ?? "http://127.0.0.1:5173",
};

if (config.host !== "127.0.0.1" && config.host !== "localhost") {
  // See docs/threat-model.md S1 — this service must never bind wider than loopback.
  throw new Error(`refusing to start: HOST must be loopback, got ${config.host}`);
}
