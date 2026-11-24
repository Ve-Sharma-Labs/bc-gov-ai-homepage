export function portFrom(value, fallback, name) {
  if (value === undefined || value === "") return fallback;
  const port = Number.parseInt(value, 10);
  if (port < 1024 || port > 65535) {
    throw new Error(`${name} must be between 1024 and 65535.`);
  }
  return port;
}
