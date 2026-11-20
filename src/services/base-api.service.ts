import { APIRequestContext, request } from "@playwright/test";
import { ApiError } from "@models/registration.model";
import { setLastApiCall } from "@helpers/allure-helper";
import { ACCEPT_LANGUAGE_HEADER } from "@test-data/constants";

export abstract class BaseApiService {
  protected baseURL: string;
  protected context: APIRequestContext | null = null;
  protected cookies: string[] = [];

  constructor(baseURL?: string) {
    this.baseURL = baseURL || process.env.BASE_URL!;
  }

  async init(): Promise<void> {
    this.context = await request.newContext({
      baseURL: this.baseURL,
      extraHTTPHeaders: this.getDefaultHeaders(),
    });
  }

  async dispose(): Promise<void> {
    if (this.context) {
      await this.context.dispose();
      this.context = null;
    }
  }

  protected getDefaultHeaders(): Record<string, string> {
    return {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...ACCEPT_LANGUAGE_HEADER.RU,
    };
  }

  protected getContext(): APIRequestContext {
    if (!this.context) {
      throw new Error(
        `${this.constructor.name} not initialized. Call init() first.`,
      );
    }
    return this.context;
  }

  protected async handleErrorResponse(
    response: any,
    operation: string,
  ): Promise<void> {
    const error: ApiError = await response.json().catch(() => ({}));
    const message =
      error.message || `HTTP ${response.status()} ${response.statusText()}`;
    const code = error.error_code || "UNKNOWN";
    throw new Error(`${operation} failed: ${message} (${code})`);
  }

  protected async checkResponse(
    response: any,
    operation: string,
  ): Promise<void> {
    if (!response.ok()) {
      await this.handleErrorResponse(response, operation);
    }
  }

  async rawRequest(
    method: "GET" | "POST" | "PUT" | "DELETE" | "PATCH",
    endpoint: string,
    data?: any,
    headers?: Record<string, string>,
  ) {
    const response = await this.getContext().fetch(endpoint, {
      method,
      data,
      headers,
    });
    this.logApiCall(method, endpoint, response, data, headers);

    const text = await response.text().catch(() => "");
    let body = null;
    try {
      body = JSON.parse(text);
    } catch {}

    return {
      status: response.status(),
      statusText: response.statusText(),
      headers: response.headers(),
      body,
      text,
    };
  }

  protected logApiCall(
    method: string,
    endpoint: string,
    response: any,
    data?: any,
    headers?: Record<string, string>,
  ) {
    setLastApiCall({
      request: {
        url: endpoint,
        method,
        headers: headers || this.getDefaultHeaders(),
        ...(data !== undefined ? { data } : {}),
      },
      response,
    });
  }
}
