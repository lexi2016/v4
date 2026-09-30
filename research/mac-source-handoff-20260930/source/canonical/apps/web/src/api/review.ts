import type { ReviewEnvelope, ManualReviewResult } from "../contracts/review";

export async function loadReview(date: string, signal?: AbortSignal): Promise<ReviewEnvelope> {
  const url = `/api/v3/review?date=${encodeURIComponent(date)}`;
  const response = signal ? await fetch(url, { signal }) : await fetch(url);
  if (!response.ok) throw new Error("review request failed");
  return response.json() as Promise<ReviewEnvelope>;
}


export async function generateReview(date: string): Promise<ManualReviewResult> {
  const response = await fetch("/api/v3/review/generate", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ date }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const messages: Record<string, string> = {
      DATE_NOT_CONFIGURED: "该日期没有单独批准的生成配置。",
      CONFIG_DATE_MISMATCH: "生成配置日期与所选日期不一致。",
      GENERATION_RUNNING: "该日期正在生成，请勿重复提交。",
      ATTEMPT_REQUIRES_REVIEW: "该日期已有生成尝试，请核对记录；未重复请求模型。",
      GENERATION_FAILED: "生成未完成，请核对本地记录；未自动重试。",
    };
    throw new Error(messages[String(body?.detail?.code)] ?? "服务端生成绑定或状态未确认，请核对配置。");
  }
  return response.json() as Promise<ManualReviewResult>;
}
