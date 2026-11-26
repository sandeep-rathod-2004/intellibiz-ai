import axios from "axios";
const apiBaseURL = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? "http://localhost:8000/api/v1" : "");
if (import.meta.env.PROD && !apiBaseURL) {
  throw new Error("VITE_API_URL must be configured for production.");
}
export const api=axios.create({baseURL:apiBaseURL});
api.interceptors.request.use(c=>{const t=localStorage.getItem("ib_token");if(t)c.headers.Authorization=`Bearer ${t}`;return c});

export interface ApiRetryInfo {
  retryable: boolean;
  retryAfterSeconds: number | null;
}

function errorDetail(error: unknown): Record<string, unknown> | null {
  if (!axios.isAxiosError<{detail?: unknown}>(error)) return null;
  const detail = error.response?.data?.detail;
  return detail && typeof detail === "object" && !Array.isArray(detail)
    ? detail as Record<string, unknown>
    : null;
}

export function errorRetryInfo(error: unknown): ApiRetryInfo {
  const detail = errorDetail(error);
  const retryAfter = detail?.retry_after_seconds;
  return {
    retryable: detail?.retryable === true,
    retryAfterSeconds: typeof retryAfter === "number" && Number.isFinite(retryAfter) && retryAfter >= 0
      ? retryAfter
      : null,
  };
}

export function errorMessage(error: unknown): string {
  if (axios.isAxiosError<{detail?: unknown}>(error)) {
    const detail = error.response?.data?.detail;
    let message: string | undefined;
    if (typeof detail === "string") {
      message = detail;
    } else if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      const providerMessage = (detail as {message?: unknown}).message;
      if (typeof providerMessage === "string") message = providerMessage;
    }
    if (Array.isArray(detail)) {
      const messages = detail.map((item: unknown) => {
        if (typeof item === "string") return item;
        if (!item || typeof item !== "object") return undefined;
        const issue = item as {loc?: unknown; msg?: unknown};
        if (typeof issue.msg !== "string") return undefined;
        const location = Array.isArray(issue.loc)
          ? issue.loc
              .filter((part): part is string | number => typeof part === "string" || typeof part === "number")
              .filter((part) => part !== "body")
              .join(".")
          : "";
        return location ? `${location}: ${issue.msg}` : issue.msg;
      }).filter((message): message is string => Boolean(message));
      if (messages.length) message = messages.join("; ");
    }
    message = message || error.message || "Something went wrong";
    const retryInfo = errorRetryInfo(error);
    if (retryInfo.retryable && retryInfo.retryAfterSeconds !== null && retryInfo.retryAfterSeconds > 0) {
      message += ` Retry after ${Math.ceil(retryInfo.retryAfterSeconds)} seconds.`;
    }
    const requestId = error.response?.headers["x-request-id"];
    return typeof requestId === "string" && requestId
      ? `${message} (Request ID: ${requestId})`
      : message;
  }
  return error instanceof Error ? error.message : "Something went wrong";
}
