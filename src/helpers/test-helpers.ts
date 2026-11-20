// Минимальный срез из реального src/helpers/test-helpers.ts
import { expect } from "@playwright/test";
import { HttpStatus, HTTP_MESSAGES } from "@test-data/constants";

export async function expectErrorResponse(
  response: any,
  expectedErrorCode?: string,
  expectedMessageFragment?: string,
  expectedStatus?: number,
) {
  const text = await response.text();
  if (!text) {
    if (expectedStatus !== undefined) {
      expect.soft(response.status()).toBe(expectedStatus);
    }
    return {};
  }

  const body = JSON.parse(text);
  if (expectedErrorCode) {
    if (body.error_code !== undefined) {
      expect.soft(body.error_code).toBe(expectedErrorCode);
    } else if (body.error !== undefined) {
      expect.soft(body.error).toBe(expectedErrorCode);
    } else {
      expect.soft(body).toHaveProperty("error_code");
    }
  }
  if (expectedMessageFragment) {
    expect.soft(body.message).toContain(expectedMessageFragment);
  }
  return body;
}

export async function expectGenericBadRequestWithoutErrorCode(response: any) {
  expect.soft(response.status()).toBe(HttpStatus.BAD_REQUEST);
  const body = await response.json();
  expect.soft(body).not.toHaveProperty("error_code");
  expect.soft(body.error).toBe(HTTP_MESSAGES[HttpStatus.BAD_REQUEST]);
}
