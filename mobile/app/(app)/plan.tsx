/**
 * Placeholder for the `plan` tab (§8.1) — T-25 replaces this with the real
 * program overview (8.2 screens 17–18). No data fetching, no API call: just
 * the empty state, so the tab has a real screen behind it instead of the
 * "Unmatched Route" fallback.
 */
import { GEmptyState, GScreen } from "../../src/components";

export default function PlanPlaceholder() {
  return (
    <GScreen>
      <GEmptyState titleKey="comingSoon.plan.title" bodyKey="comingSoon.plan.body" />
    </GScreen>
  );
}
