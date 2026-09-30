import type { ResearchEnvelope } from "../contracts/research";

async function load(url: string): Promise<ResearchEnvelope> {
  const response = await fetch(url);
  if (!response.ok) throw new Error("research request failed");
  return response.json() as Promise<ResearchEnvelope>;
}

export function loadResearchExact(archiveDate: string): Promise<ResearchEnvelope> {
  return load(`/api/v3/research/articles?archive_date=${encodeURIComponent(archiveDate)}`);
}

export function loadResearchLatest(): Promise<ResearchEnvelope> {
  return load("/api/v3/research/articles/latest");
}
