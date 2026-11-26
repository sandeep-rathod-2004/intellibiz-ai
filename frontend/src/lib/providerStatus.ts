export type CopilotProviderState =
  | "operational"
  | "authentication_verified"
  | "configured"
  | "configuration_required"
  | "authentication_failed"
  | "access_restricted"
  | "quota_exceeded"
  | "rate_limited"
  | "organization_spend_limit_exceeded"
  | "project_spend_limit_exceeded"
  | "organization_usage_limit_reached"
  | "unknown_restriction"
  | "local_analytics"
  | "model_unavailable"
  | "temporarily_unavailable"
  | "unavailable";

const labels: Record<CopilotProviderState, string> = {
  operational: "AI available",
  authentication_verified: "AI auth verified · model untested",
  configured: "AI configured · not tested",
  configuration_required: "AI not configured",
  authentication_failed: "AI authentication failed",
  access_restricted: "AI access restricted",
  quota_exceeded: "API quota unavailable",
  rate_limited: "Temporary rate limit",
  organization_spend_limit_exceeded: "Organization spending limit reached",
  project_spend_limit_exceeded: "Project spending limit reached",
  organization_usage_limit_reached: "Organization usage limit reached",
  unknown_restriction: "Unknown provider restriction",
  local_analytics: "Local analytics only",
  model_unavailable: "AI model unavailable",
  temporarily_unavailable: "Provider unavailable",
  unavailable: "Provider unavailable",
};

export function copilotProviderStatusLabel(
  status: CopilotProviderState | null | undefined,
): string {
  return status ? labels[status] : "Checking AI…";
}
