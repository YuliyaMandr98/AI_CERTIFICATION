// Урезанная версия реального src/services/deposits.service.ts
import {
  HTTP_METHODS,
  DEPOSIT_CALCULATOR_ENDPOINT,
  DEPOSITS_ENDPOINT,
  DEPOSIT_TOP_UP_DATE_LIMITS_ENDPOINT,
} from "@test-data/constants";
import { BaseApiService } from "./base-api.service";

export class DepositsService extends BaseApiService {
  constructor(baseURL?: string) {
    super(baseURL || process.env.BASE_URL);
  }

  private buildUrl(endpoint: string): string {
    const normalizedBase = this.baseURL.endsWith("/")
      ? this.baseURL
      : `${this.baseURL}/`;
    return new URL(endpoint, normalizedBase).toString();
  }

  async pushRequest(
    endpoint: string,
    accessToken?: string,
    options?: { method?: "get" | "post" | "put" | "delete"; data?: any },
  ) {
    const requestUrl = this.buildUrl(endpoint);
    const headers: Record<string, string> = {};
    if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
    const method = (options?.method || HTTP_METHODS.GET).toLowerCase();

    let response;
    if (method === HTTP_METHODS.GET)
      response = await this.getContext().get(requestUrl, { headers });
    else if (method === HTTP_METHODS.POST)
      response = await this.getContext().post(requestUrl, {
        data: options?.data,
        headers,
      });
    else throw new Error(`Unsupported HTTP method: ${method}`);

    const status = response.status();
    this.logApiCall(method.toUpperCase(), requestUrl, response, options?.data, headers);
    let body: any = undefined;
    try {
      body = await response.json();
    } catch (e) {}
    return { status, response, body };
  }

  // US-9.2.1 | Депозитный калькулятор доходности

  async calculateDeposit(
    body: Partial<{
      product_id: number;
      currency_id: number;
      amount: number | string;
      term_months: number | string;
      top_up_enabled: boolean;
      monthly_top_up_amount: number | string | null;
      top_up_date: string | null;
    }>,
    accessToken?: string,
  ) {
    return this.pushRequest(DEPOSIT_CALCULATOR_ENDPOINT, accessToken, {
      method: HTTP_METHODS.POST,
      data: body,
    });
  }

  /** Условия конкретного продукта по валюте из каталога депозитных продуктов */
  async getProductCurrencyConditions(
    productId: number,
    currencyCode: string,
    accessToken?: string,
  ) {
    const { body } = await this.pushRequest(DEPOSITS_ENDPOINT, accessToken);
    const product = body?.items?.find((p: any) => p.product_id === productId);
    return product?.currency_conditions?.find(
      (cc: any) => cc.currency_code === currencyCode,
    );
  }

  static validateCalculateResponseStructure(body: any): string[] {
    const failed: string[] = [];
    if (!body || typeof body !== "object") return ["root_not_object"];
    if (typeof body.product_id !== "number") failed.push("product_id");
    if (typeof body.currency_id !== "number") failed.push("currency_id");
    if (typeof body.interest_rate !== "number") failed.push("interest_rate");
    if (body.bonus_rate !== null && typeof body.bonus_rate !== "number")
      failed.push("bonus_rate");
    if (typeof body.initial_amount !== "number") failed.push("initial_amount");
    if (typeof body.expected_income !== "number") failed.push("expected_income");
    if (body.bonus_income !== null && typeof body.bonus_income !== "number")
      failed.push("bonus_income");
    if (typeof body.total_amount_at_end !== "number")
      failed.push("total_amount_at_end");
    if (typeof body.term_months !== "number") failed.push("term_months");
    return failed;
  }

  static buildAmountTermBoundaryCases(conditions: {
    min_amount: number;
    max_amount: number;
    min_term: number;
    max_term: number;
  }): Array<[string, number, number]> {
    return [
      ["amount = min_amount", conditions.min_amount, conditions.min_term],
      ["amount = max_amount", conditions.max_amount, conditions.min_term],
      ["term = min_term", conditions.min_amount + 1000, conditions.min_term],
      ["term = max_term", conditions.min_amount + 1000, conditions.max_term],
    ];
  }

  async getDepositTopUpDateLimits(accessToken?: string) {
    return this.pushRequest(DEPOSIT_TOP_UP_DATE_LIMITS_ENDPOINT, accessToken);
  }
}
