export type Theme = "light" | "dark" | "system";
export const themeStorageKey = "bc-service-theme";

export function validTheme(value: unknown): Theme {
  return value === "light" || value === "dark" ? value : "system";
}

export function resolveTheme(preference: Theme, darkSystem: boolean): "light" | "dark" {
  return preference === "system" ? (darkSystem ? "dark" : "light") : preference;
}

// Only the theme preference is persisted; never prompts, answers, or checklist state.
export const themeBootstrap = `(function(){try{var p=localStorage.getItem("${themeStorageKey}");var t=p==="light"||p==="dark"?p:"system";var d=t==="system"?matchMedia("(prefers-color-scheme: dark)").matches:t==="dark";document.documentElement.dataset.theme=d?"dark":"light";document.documentElement.dataset.preference=t;document.documentElement.style.colorScheme=d?"dark":"light"}catch(e){}})()`;
