import type { ReviewEnvelope } from "../contracts/review";

export async function loadReview(date: string, signal?: AbortSignal): Promise<ReviewEnvelope> {
  const url = `/api/v3/review?date=${encodeURIComponent(date)}`;
  const response = signal ? await fetch(url, { signal }) : await fetch(url);
  if (!response.ok) throw new Error("review request failed");
  return response.json() as Promise<ReviewEnvelope>;
}
