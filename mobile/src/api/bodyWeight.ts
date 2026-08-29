/**
 * §5.10 (PUT/GET/DELETE /body-weight), P2-FR-009/010, P2-ADR-06. Types are
 * generated from backend/openapi.json via `schema.d.ts`; the authoritative
 * source is backend/app/schemas/metrics.py's `BodyWeight*` models.
 *
 * `entries`/`moving_average_7d` deliberately carry only `measured_on`/
 * `weight_kg` (schemas/metrics.py's own documented reasoning: neither DELETE
 * -- keyed by `measured_on` -- nor a future PUT -- an upsert, also keyed by
 * `measured_on` -- ever needs a row id). The single upserted `entry` PUT
 * returns is the fuller row shape instead.
 */
import { client } from "./client";
import type { components, paths } from "./schema";

type Schemas = components["schemas"];

export type BodyWeightPoint = Schemas["BodyWeightPoint"];
export type BodyWeightSummary = Schemas["BodyWeightSummaryData"];
export type BodyWeightListResponse = Schemas["BodyWeightListResponse"];
export type BodyWeightEntryData = Schemas["BodyWeightEntryData"];
export type BodyWeightUpsertResponse = Schemas["BodyWeightUpsertResponse"];

/**
 * Query parameters, not a body: they live under `paths` in the generated
 * schema rather than `components.schemas`, so they are read from there. Both
 * are optional -- omitting `from` takes the server's own 90-day default and
 * omitting `to` means "today" in the caller's timezone.
 */
export type BodyWeightRangeParams = NonNullable<
  paths["/api/v1/body-weight"]["get"]["parameters"]["query"]
>;

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
