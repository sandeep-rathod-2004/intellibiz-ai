import assert from "node:assert/strict";
import test from "node:test";
import {transportErrorMessage} from "./transportError.ts";

test("explains a connection failure with the API host and CORS origin to check", () => {
  const message = transportErrorMessage({
    code: "ERR_NETWORK",
    baseURL: "https://api.example.test/api/v1",
    requestURL: "/copilot/conversations",
    browserOrigin: "https://app.example.test",
  });
  assert.match(message, /could not reach the IntelliBiz API at https:\/\/api\.example\.test/);
  assert.match(message, /CORS_ORIGINS allows https:\/\/app\.example\.test/);
  assert.doesNotMatch(message, /Network Error/);
});

test("reports timeouts and canceled requests distinctly", () => {
  assert.match(transportErrorMessage({code: "ECONNABORTED"}), /timed out/);
  assert.match(transportErrorMessage({code: "ERR_CANCELED"}), /request was canceled/);
});
