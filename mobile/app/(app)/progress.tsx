/**
 * Placeholder for the `progress` tab (§8.1) — T-28 replaces this with the
 * real weight log and chart (8.2 screen 22). No data fetching, no API call:
 * just the empty state, so the tab has a real screen behind it instead of
 * the "Unmatched Route" fallback.
 */
import { GEmptyState, GScreen } from "../../src/components";

export default function ProgressPlaceholder() {
  return (
    <GScreen>
      <GEmptyState titleKey="comingSoon.progress.title" bodyKey="comingSoon.progress.body" />
    </GScreen>
  );
}
