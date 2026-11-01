import { spawn } from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const args = process.argv.slice(2);
if (process.env.LOCAL_EVIDENCE_EVALUATION_ENABLED === "true" && ["dev", "start"].includes(args[0])) {
  const flag = args.findIndex((value) => ["--hostname", "-H"].includes(value));
  const host = flag >= 0 ? args[flag + 1] : args.find((value) => value.startsWith("--hostname="))?.slice(11);
  if (!host || !["127.0.0.1", "::1", "localhost"].includes(host)) {
    throw new Error("Local source evaluation must listen on an explicit loopback hostname.");
  }
  process.env.HOSTNAME = host;
}
const child = spawn(process.execPath, [require.resolve("next/dist/bin/next"), ...args], {
  env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1" },
  stdio: "inherit",
});

for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
child.on("error", (error) => {
  console.error(`Next.js could not start: ${error.message}`);
  process.exitCode = 1;
});
child.on("exit", (code) => { process.exitCode = code ?? 1; });
