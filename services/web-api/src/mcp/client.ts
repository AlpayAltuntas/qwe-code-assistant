import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

import { config } from "../config.js";

// Spawns services/mcp-server fresh per call, same as Continue does — this
// is a thin second client of the Phase 4/5 tool contract, not a parallel
// implementation of any EDI logic (docs/threat-model.md E3). No caching
// of a long-lived connection: simpler to reason about for a single-user
// local tool with light request volume, at the cost of one Python
// interpreter startup per call.
export async function callMcpTool<T = unknown>(
  toolName: string,
  args: Record<string, unknown>,
): Promise<T> {
  const transport = new StdioClientTransport({
    command: "uv",
    args: ["run", "--directory", config.mcpServerDir, "edi-mcp-server"],
  });
  const client = new Client({ name: "qwe-web-api", version: "0.1.0" });

  try {
    await client.connect(transport);
    const result = await client.callTool({ name: toolName, arguments: args });
    if (result.isError) {
      const text = extractText(result.content);
      throw new Error(`MCP tool ${toolName} returned an error: ${text}`);
    }
    const text = extractText(result.content);
    return JSON.parse(text) as T;
  } finally {
    await client.close();
  }
}

function extractText(content: unknown): string {
  if (Array.isArray(content)) {
    const first = content.find(
      (block): block is { type: "text"; text: string } =>
        typeof block === "object" && block !== null && (block as { type?: string }).type === "text",
    );
    if (first) return first.text;
  }
  return JSON.stringify(content);
}
