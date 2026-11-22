import { readFileSync } from "node:fs";
import { IntercomClient } from "../../vendor/agent-intercom-pi/broker/client.ts";
import { spawnBrokerIfNeeded } from "../../vendor/agent-intercom-pi/broker/spawn.ts";

function arg(name: string): string | undefined {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

const cwd = arg("--cwd");
const list = process.argv.includes("--list");
await spawnBrokerIfNeeded("npx", ["--no-install", "tsx"]);
const client = new IntercomClient();
const now = Date.now();
await client.connect({ name: "agentcomms", cwd: process.cwd(), model: "harness", pid: process.pid, startedAt: now,
                       lastActivity: now });
try {
  const sessions = await client.listSessions();
  if (list) {
    console.log(JSON.stringify(sessions.map((s) => ({ id: s.id, name: s.name, cwd: s.cwd, pid: s.pid }))));
  } else {
    const target = sessions.find((s) => s.cwd === cwd);
    if (!target) {
      console.log(JSON.stringify({ accepted: false, delivered: false, reason: `no intercom session with cwd ${cwd}` }));
      process.exitCode = 2;
    } else {
      const result = await client.send(target.id, { text: readFileSync(0, "utf-8") });
      console.log(JSON.stringify({ ...result, to: target.id, name: target.name }));
      process.exitCode = result.accepted ? 0 : 1;
    }
  }
} finally {
  await client.disconnect();
}
