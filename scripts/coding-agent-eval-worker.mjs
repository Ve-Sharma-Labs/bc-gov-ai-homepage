import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

// Only inputs enter this process. Expected results stay in the trusted grader.
const request = JSON.parse(readFileSync(0, "utf8"));
const candidate = await import(pathToFileURL(process.argv[2]).href);
const results = [];
for (const invocation of request.invocations) {
  const fn = candidate[invocation.function];
  if (typeof fn !== "function") throw new Error("Missing required export");
  try {
    const value = await fn(...invocation.args);
    results.push(value === undefined
      ? { kind: "return", undefined: true }
      : { kind: "return", value });
  } catch {
    results.push({ kind: "throw" });
  }
}
process.stdout.write(JSON.stringify({ results }));
