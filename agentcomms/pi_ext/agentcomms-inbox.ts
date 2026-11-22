import * as fs from "node:fs";
import * as net from "node:net";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export const TURN_MARKER = "agentcomms-turn";
const MAX_BYTES = 1024 * 1024;

export function replyFor(compacting: boolean, empty: boolean): string {
	if (empty) return "error empty message\n";
	return compacting ? "error compacting\n" : "queued followUp\n";
}

export default function agentcommsInbox(pi: ExtensionAPI) {
	const socketPath = process.env.AGENTCOMMS_PI_SOCKET;
	if (!socketPath) return;
	let server: net.Server | undefined;
	let compacting = false;

	// followUp starts a turn when idle and queues when busy; failures only surface asynchronously, so never claim delivery
	const accept = (text: string): string => {
		const reply = replyFor(compacting, !text);
		if (reply.startsWith("queued")) pi.sendUserMessage(text, { deliverAs: "followUp" });
		return reply;
	};

	const serve = () => {
		if (server) return;
		fs.rmSync(socketPath, { force: true });
		server = net.createServer({ allowHalfOpen: true }, (conn) => {
			const chunks: Buffer[] = [];
			let size = 0;
			conn.on("data", (chunk: Buffer) => {
				size += chunk.length;
				if (size > MAX_BYTES) conn.destroy();
				else chunks.push(chunk);
			});
			conn.on("end", () => conn.end(accept(Buffer.concat(chunks).toString("utf8"))));
			conn.on("error", () => undefined);
		});
		server.listen(socketPath, () => fs.chmodSync(socketPath, 0o600));
	};

	pi.on("session_start", async () => serve());
	pi.on("session_before_compact", async () => {
		compacting = true;
	});
	pi.on("session_compact", async () => {
		compacting = false;
	});
	pi.on("session_compact_failed", async () => {
		compacting = false;
	});
	pi.on("agent_start", async () => pi.appendEntry(TURN_MARKER, { state: "busy" }));
	pi.on("agent_end", async () => pi.appendEntry(TURN_MARKER, { state: "idle" }));
	pi.on("session_shutdown", async () => {
		server?.close();
		server = undefined;
		fs.rmSync(socketPath, { force: true });
	});
}
