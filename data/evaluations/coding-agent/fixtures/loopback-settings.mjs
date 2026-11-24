function portFrom(value, fallback, name) {
  if (value === undefined || value === "") return fallback;
  if (!/^\d+$/.test(value)) throw new Error(`${name} must be a whole-number port.`);
  const port = Number(value);
  if (port < 1024 || port > 65535) {
    throw new Error(`${name} must be between 1024 and 65535.`);
  }
  return port;
}

export function localSettings(env = {}) {
  const webPort = portFrom(env.WEB_PORT, 3000, "WEB_PORT");
  const apiPort = portFrom(env.API_PORT, 8000, "API_PORT");
  return {
    webPort,
    apiPort,
    webUrl: `http://0.0.0.0:${webPort}`,
    apiUrl: `http://0.0.0.0:${apiPort}`,
  };
}
