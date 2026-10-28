import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ThemeControl } from "@/components/theme-control";
import { resolveTheme, themeBootstrap, themeStorageKey, validTheme } from "@/lib/theme";

describe("appearance preferences", () => {
  it("defaults to the device, and validates stored preferences", () => {
    expect(validTheme("invalid")).toBe("system");
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });

  it("applies an explicit stored preference before the UI hydrates", () => {
    localStorage.setItem(themeStorageKey, "dark");
    window.eval(themeBootstrap);
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.style.colorScheme).toBe("dark");
  });

  it("preserves the bootstrap theme and persists keyboard selection", async () => {
    const user = userEvent.setup();
    localStorage.setItem(themeStorageKey, "dark");
    window.eval(themeBootstrap);
    render(<ThemeControl />);
    await waitFor(() => expect(screen.getByRole("radio", { name: "Dark theme" })).toBeChecked());
    expect(document.documentElement.dataset.theme).toBe("dark");
    screen.getByRole("radio", { name: "Dark theme" }).focus();
    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("radio", { name: "Light theme" })).toBeChecked();
    expect(localStorage.getItem(themeStorageKey)).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("updates system mode when the device preference changes", async () => {
    let listener: () => void = () => {};
    const media = {
      matches: false, media: "", onchange: null,
      addEventListener: vi.fn((_event, handler) => { listener = handler; }),
      removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
    };
    vi.spyOn(window, "matchMedia").mockReturnValue(media);
    render(<ThemeControl />);
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe("light"));
    media.matches = true;
    act(() => listener());
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("survives unavailable local storage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("Storage denied"); });
    expect(() => window.eval(themeBootstrap)).not.toThrow();
    expect(() => render(<ThemeControl />)).not.toThrow();
  });
});
