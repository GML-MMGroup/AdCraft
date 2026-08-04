import { verifySkillBundle } from "./skills.js";

interface ListenableServer {
  listen(port: number, host: string): unknown;
}

export async function startVerifiedServer(
  server: ListenableServer,
  port: number,
  host: string,
  verify: () => Promise<unknown> = verifySkillBundle,
): Promise<void> {
  await verify();
  server.listen(port, host);
}
