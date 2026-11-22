import { appendFileSync, existsSync, unlinkSync } from "node:fs";

const PROTOCOL_VERSION = "2025-06-18";
const socketPath = process.env.AGENTCOMMS_CHANNEL_SOCKET ?? "";
const logPath = process.env.AGENTCOMMS_CHANNEL_LOG ?? "";

type Json = Record<string, unknown>;

function log(line: string): void {
  if (logPath) appendFileSync(logPath, `${(Date.now() / 1000).toFixed(3)} ${line}\n`);
}

function write(message: Json): void {
  process.stdout.write(`${JSON.stringify({ jsonrpc: "2.0", ...message })}\n`);
}

export function reply(request: Json): Json | null {
  const id = request.id;
  if (id === undefined || id === null) return null;
  switch (request.method) {
    case "initialize":
      return {
        id,
        result: {
          protocolVersion: PROTOCOL_VERSION,
          capabilities: { experimental: { "claude/channel": {} }, tools: {} },
          serverInfo: { name: "agentcomms", version: "0.1" },
          instructions: "Messages from the agentcomms harness arrive as <channel source=\"agentcomms\"> events.",
        },
      };
    case "tools/list":
      return { id, result: { tools: [] } };
    case "ping":
      return { id, result: {} };
    default:
      return { id, error: { code: -32601, message: `method not found: ${String(request.method)}` } };
  }
}

export function channelNotification(content: string, meta: Record<string, string>): Json {
  return { method: "notifications/claude/channel", params: { content, meta } };
}

function onStdin(): void {
  let buffer = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk: string) => {
    buffer += chunk;
    let newline = buffer.indexOf("\n");
    while (newline >= 0) {
      const line = buffer.slice(0, newline);
      buffer = buffer.slice(newline + 1);
      newline = buffer.indexOf("\n");
      if (!line.trim()) continue;
      try {
        const request = JSON.parse(line) as Json;
        log(`mcp <- ${String(request.method ?? "response")}`);
        const answer = reply(request);
        if (answer) write(answer);
      } catch {
        log("mcp <- unparseable line");
      }
    }
  });
  process.stdin.on("end", () => process.exit(0));
}

function removeSocket(): void {
  if (socketPath && existsSync(socketPath)) unlinkSync(socketPath);
}

function listen(): void {
  if (!socketPath) return;
  removeSocket();
  process.on("exit", removeSocket);
  for (const signal of ["SIGTERM", "SIGINT", "SIGHUP"] as const) process.on(signal, () => process.exit(0));
  Bun.listen<{ decoder: TextDecoder; chunks: string[] }>({
    unix: socketPath,
    socket: {
      open(socket) {
        socket.data = { decoder: new TextDecoder(), chunks: [] };
      },
      data(socket, data) {
        socket.data.chunks.push(socket.data.decoder.decode(data, { stream: true }));
      },
      end(socket) {
        const content = socket.data.chunks.join("") + socket.data.decoder.decode();
        if (content) {
          write(channelNotification(content, { sender: "agentcomms" }));
          log(`channel -> ${content.length} chars`);
        }
        socket.write(content ? "emitted\n" : "empty\n");
        socket.end();
      },
      error(_socket, error) {
        log(`socket error ${error.message}`);
      },
    },
  });
  log(`listening ${socketPath}`);
}

if (import.meta.main) {
  onStdin();
  listen();
}
