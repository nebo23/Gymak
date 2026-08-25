import { describe, expect, it } from "vitest";

import {
  DEFAULT_THEME_PREFERENCE,
  THEME_PREFERENCES,
  parseThemePreference,
  resolveScheme,
} from "./themePreference";

describe("parseThemePreference", () => {
  it("accepts the three known values", () => {
    expect(parseThemePreference("system")).toBe("system");
    expect(parseThemePreference("light")).toBe("light");
    expect(parseThemePreference("dark")).toBe("dark");
  });

  it("defaults to system when nothing is stored", () => {
    expect(parseThemePreference(null)).toBe("system");
    expect(parseThemePreference(undefined)).toBe("system");
  });

  it("defaults to system on an unrecognised stored value", () => {
    expect(parseThemePreference("")).toBe("system");
    expect(parseThemePreference("Dark")).toBe("system");
    expect(parseThemePreference("solarized")).toBe("system");
  });

  it("exposes system as the documented default", () => {
    expect(DEFAULT_THEME_PREFERENCE).toBe("system");
    expect(THEME_PREFERENCES).toEqual(["system", "light", "dark"]);
  });
});

describe("resolveScheme", () => {
  it("follows the OS in system mode", () => {
    expect(resolveScheme("system", "dark")).toBe("dark");
    expect(resolveScheme("system", "light")).toBe("light");
  });

  it("falls back to light when the OS reports no scheme", () => {
    expect(resolveScheme("system", null)).toBe("light");
    expect(resolveScheme("system", undefined)).toBe("light");
    expect(resolveScheme("system", "unspecified")).toBe("light");
  });

  it("ignores the OS entirely once a theme is forced", () => {
    for (const osScheme of ["light", "dark", "unspecified", null, undefined] as const) {
      expect(resolveScheme("light", osScheme)).toBe("light");
      expect(resolveScheme("dark", osScheme)).toBe("dark");
    }
  });
});
