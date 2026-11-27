export interface TransportFailure {
  code?: string;
  baseURL?: string;
  requestURL?: string;
  browserOrigin?: string;
}

export function transportErrorMessage(failure: TransportFailure): string {
  if (failure.code === "ECONNABORTED" || failure.code === "ETIMEDOUT") {
    return "The request to IntelliBiz AI timed out. Check the backend service and try again.";
  }
  if (failure.code === "ERR_CANCELED") {
    return "The request was canceled before the server responded.";
  }

  let apiOrigin = "";
  try {
    if (failure.baseURL) {
      apiOrigin = new URL(failure.requestURL ?? "", failure.baseURL).origin;
    }
  } catch {
    // Keep diagnostics useful without echoing malformed or credential-bearing URLs.
  }
  const apiTarget = apiOrigin ? ` at ${apiOrigin}` : "";
  const originCheck = failure.browserOrigin
    ? ` Confirm backend CORS_ORIGINS allows ${failure.browserOrigin}.`
    : " Confirm the backend CORS allowlist includes this frontend.";
  return `The browser could not reach the IntelliBiz API${apiTarget}. Check network access and that the backend is available.${originCheck}`;
}
