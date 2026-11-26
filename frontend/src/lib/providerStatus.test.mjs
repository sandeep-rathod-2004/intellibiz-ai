import assert from "node:assert/strict";
import test from "node:test";
import {copilotProviderStatusLabel} from "./providerStatus.ts";

test("labels provider health separately from backend data API health", () => {
  assert.equal(copilotProviderStatusLabel("operational"), "AI available");
  assert.equal(
    copilotProviderStatusLabel("authentication_failed"),
    "AI authentication failed",
  );
  assert.equal(copilotProviderStatusLabel("access_restricted"), "AI access restricted");
  assert.equal(copilotProviderStatusLabel("quota_exceeded"), "API quota unavailable");
  assert.equal(copilotProviderStatusLabel("rate_limited"), "Temporary rate limit");
  assert.equal(
    copilotProviderStatusLabel("project_spend_limit_exceeded"),
    "Project spending limit reached",
  );
  assert.equal(
    copilotProviderStatusLabel("organization_spend_limit_exceeded"),
    "Organization spending limit reached",
  );
  assert.equal(
    copilotProviderStatusLabel("organization_usage_limit_reached"),
    "Organization usage limit reached",
  );
  assert.equal(
    copilotProviderStatusLabel("unknown_restriction"),
    "Unknown provider restriction",
  );
  assert.equal(copilotProviderStatusLabel("local_analytics"), "Local analytics only");
  assert.equal(
    copilotProviderStatusLabel("temporarily_unavailable"),
    "Provider unavailable",
  );
});

test("does not imply a models-list authentication check proves inference access", () => {
  assert.equal(
    copilotProviderStatusLabel("authentication_verified"),
    "AI auth verified · model untested",
  );
  assert.equal(
    copilotProviderStatusLabel("configured"),
    "AI configured · not tested",
  );
});

test("shows unconfigured and checking states explicitly", () => {
  assert.equal(copilotProviderStatusLabel("configuration_required"), "AI not configured");
  assert.equal(copilotProviderStatusLabel(null), "Checking AI…");
});
