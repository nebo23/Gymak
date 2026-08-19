/**
 * §5.10 (PUT/GET/DELETE /body-weight), P2-FR-009/010, P2-ADR-06. See
 * backend/app/schemas/metrics.py's `BodyWeight*` models for the
 * authoritative shapes -- read directly from that file, not inferred.
 *
 * `entries`/`moving_average_7d` deliberately carry only `measured_on`/
 * `weight_kg` (schemas/metrics.py's own documented reasoning: neither DELETE
 * -- keyed by `measured_on` -- nor a future PUT -- an upsert, also keyed by
 * `measured_on` -- ever needs a row id). The single upserted `entry` PUT
 * returns is the fuller row shape instead.
 */
import { client } from "./client";

export interface BodyWeightPoint {
  measured_on: string;
  weight_kg: number;
}

export interface BodyWeightSummary {
  first: number | null;
  latest: number | null;
  change_kg: number | null;
  entry_count: number;
}

export interface BodyWeightListResponse {
  entries: BodyWeightPoint[];
  moving_average_7d: BodyWeightPoint[];
  summary: BodyWeightSummary;
}

export interface BodyWeightEntryData {
  id: string;
  measured_on: string;
  weight_kg: number;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface BodyWeightUpsertResponse {
  entry: BodyWeightEntryData;
  /** §5.10: true when this entry was the newest and therefore updated
   * `profiles.weight_kg` too (P2-ADR-06). The caller invalidates its own
   * cached profile/dashboard queries on every successful write regardless --
   * simpler than branching on this flag, and never wrong to over-invalidate
   * a query that didn't actually change. */
  profile_weight_updated: boolean;
}

export interface BodyWeightRangeParams {
  /** ISO date, inclusive. Omit for the server's own 90-day default. */
  from?: string;
  /** ISO date, inclusive. Omit for "today" in the caller's own timezone. */
  to?: string;
}

export async function listBodyWeight(
  params: BodyWeightRangeParams = {},
): Promise<BodyWeightListResponse> {
  const response = await client.get<BodyWeightListResponse>("/body-weight", { params });
  return response.data;
}

/** §5.10 PUT. Same-day writes replace (P2-ADR-06) -- calling this twice for
 * the same `measured_on` upserts, never creates a second entry. */
export async function upsertBodyWeight(input: {
  measured_on: string;
  weight_kg: number;
}): Promise<BodyWeightUpsertResponse> {
  const response = await client.put<BodyWeightUpsertResponse>("/body-weight", {
    measured_on: input.measured_on,
    weight_kg: input.weight_kg,
    note: null,
  });
  return response.data;
}

export async function deleteBodyWeight(measuredOn: string): Promise<void> {
  await client.delete(`/body-weight/${measuredOn}`);
}
