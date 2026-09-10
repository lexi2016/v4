import type {
  GlobalIndustryDatesResponse,
  GlobalIndustryResponse,
} from "../contracts/globalIndustries";

export async function loadGlobalIndustryDates(
  signal?: AbortSignal,
): Promise<GlobalIndustryDatesResponse> {
  const response = await fetch("/api/v3/research/dates", {
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw new Error("global industry dates request failed");
  return response.json() as Promise<GlobalIndustryDatesResponse>;
}

export async function loadGlobalIndustries(
  researchDate: string,
  signal?: AbortSignal,
): Promise<GlobalIndustryResponse> {
  const response = await fetch(
    `/api/v3/research/us-market?research_date=${encodeURIComponent(researchDate)}`,
    { cache: "no-store", signal },
  );
  if (!response.ok) throw new Error("global industry request failed");
  return response.json() as Promise<GlobalIndustryResponse>;
}
