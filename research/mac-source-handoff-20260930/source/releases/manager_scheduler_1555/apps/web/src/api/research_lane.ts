// Research decision-desk lane API (aligned to the V3 research lane).
export interface ResearchLane {
  research_date: string;
  endpoint_mode: string;
  schema_version: string;
  stock_research_daily?: Array<Record<string, unknown>>;
  stock_research_timeline?: Array<Record<string, unknown>>;
  research_pool_bridge?: Array<Record<string, unknown>>;
  morning_news?: Record<string, unknown>;
  news_workbench?: Record<string, unknown>;
  zsxq_hourly?: Record<string, unknown>;
  ocr_ingestion?: Record<string, unknown>;
  external_finance?: Record<string, unknown>;
  ai_news?: Record<string, unknown>;
  research_quality_summary?: Record<string, unknown>;
  key_investment_messages?: Array<Record<string, unknown>>;
  research_intelligence_timeline?: Record<string, unknown>;
  hourly_research?: Record<string, unknown>;
  cannot_confirm?: Array<unknown>;
  production_allowed?: boolean;
  [key: string]: unknown;
}

async function load(url: string): Promise<ResearchLane> {
  const response = await fetch(url);
  if (!response.ok) throw new Error("research lane request failed");
  return response.json() as Promise<ResearchLane>;
}

export function loadResearchLane(researchDate: string): Promise<ResearchLane> {
  return load(`/api/v3/research/lane?research_date=${encodeURIComponent(researchDate)}`);
}

export function loadResearchLaneLatest(): Promise<ResearchLane> {
  return load("/api/v3/research/lane");
}
