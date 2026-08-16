/**
 * §4.2's ownership note: the device zone syncs once, only while the stored
 * value is still the untouched server default, and never overwrites a real
 * one. These four cases are the ones that matter — see T-23's report.
 */
import { describe, expect, it } from "vitest";

import { SERVER_DEFAULT_TIMEZONE, shouldSyncDeviceTimezone } from "./timezoneSync";

describe("shouldSyncDeviceTimezone", () => {
  it("patches when the stored value is still the server default and the device differs", () => {
    expect(
      shouldSyncDeviceTimezone({
        storedTimezone: SERVER_DEFAULT_TIMEZONE,
        deviceTimezone: "Asia/Dubai",
      }),
    ).toBe(true);
  });

  it("never patches when the stored value is already a real, non-default zone", () => {
    expect(
      shouldSyncDeviceTimezone({
        storedTimezone: "Asia/Dubai",
        deviceTimezone: "Europe/London",
      }),
    ).toBe(false);
  });

  it("never patches when the device zone is unavailable", () => {
    expect(
      shouldSyncDeviceTimezone({
        storedTimezone: SERVER_DEFAULT_TIMEZONE,
        deviceTimezone: null,
      }),
    ).toBe(false);
    expect(
      shouldSyncDeviceTimezone({
        storedTimezone: SERVER_DEFAULT_TIMEZONE,
        deviceTimezone: undefined,
      }),
    ).toBe(false);
  });

  it("never patches when the device zone already matches the stored value", () => {
    expect(
      shouldSyncDeviceTimezone({
        storedTimezone: SERVER_DEFAULT_TIMEZONE,
        deviceTimezone: SERVER_DEFAULT_TIMEZONE,
      }),
    ).toBe(false);
  });
});
