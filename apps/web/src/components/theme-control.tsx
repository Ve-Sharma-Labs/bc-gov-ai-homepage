"use client";

import { useEffect, useState } from "react";
import { Radio, RadioGroup } from "react-aria-components";
import { Monitor, Moon, Sun } from "lucide-react";
import { resolveTheme, themeStorageKey, type Theme, validTheme } from "@/lib/theme";

export function ThemeControl() {
  const [preference, setPreference] = useState<Theme | null>(null);

  useEffect(() => {
    let initial: Theme = "system";
    try { initial = validTheme(localStorage.getItem(themeStorageKey)); } catch { /* Storage is optional. */ }
    setPreference(initial);
    const sync = (event: StorageEvent) => {
      if (event.key === themeStorageKey || event.key === null) setPreference(validTheme(event.newValue));
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);

  useEffect(() => {
    if (preference === null) return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const resolved = resolveTheme(preference, media.matches);
      document.documentElement.dataset.theme = resolved;
      document.documentElement.dataset.preference = preference;
      document.documentElement.style.colorScheme = resolved;
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [preference]);

  const change = (value: string) => {
    const theme = validTheme(value);
    setPreference(theme);
    try { localStorage.setItem(themeStorageKey, theme); } catch { /* Private browsing may deny storage. */ }
  };

  return (
    <RadioGroup className="theme-control" aria-label="Appearance" value={preference ?? "system"} onChange={change} orientation="horizontal">
      {([
        ["light", "Light", Sun],
        ["dark", "Dark", Moon],
        ["system", "System", Monitor],
      ] as const).map(([value, label, Icon]) => (
        <Radio key={value} value={value} className="theme-option" aria-label={`${label} theme`}>
          <Icon size={17} strokeWidth={1.7} aria-hidden="true" />
          <span className="theme-label">{label}</span>
        </Radio>
      ))}
    </RadioGroup>
  );
}
