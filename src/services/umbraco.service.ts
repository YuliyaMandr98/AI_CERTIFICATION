// Урезанная версия реального src/services/umbraco.service.ts
import {
  DATA_TYPES,
  HEADERS,
  PRODUCT_TYPE,
  SEARCH_DATA,
  UMBRACO_CONTENT_ENDPOINT,
  UMBRACO_ITEM_ENDPOINT,
} from "@test-data/constants";
import { BaseApiService } from "./base-api.service";
import { request } from "@playwright/test";

export class UmbracoService extends BaseApiService {
  constructor(baseURL?: string) {
    super(baseURL || process.env.UMBRACO_CMS);
  }

  async init(): Promise<void> {
    this.context = await request.newContext({
      baseURL: this.baseURL,
      extraHTTPHeaders: this.getDefaultHeaders(),
      ignoreHTTPSErrors: true,
    });
  }

  async getItem(
    identifier: string,
    params?: string,
    headers?: Record<string, string>,
  ) {
    let endpoint = `${UMBRACO_ITEM_ENDPOINT}${identifier}`;
    if (params) endpoint += `?${params}`;
    return await this.rawRequest("GET", endpoint, undefined, headers);
  }

  async getContent(
    params?: Record<string, any>,
    headers?: Record<string, string>,
  ) {
    let endpoint = UMBRACO_CONTENT_ENDPOINT;
    if (params) {
      const query = Object.entries(params)
        .map(([k, v]) => {
          if (Array.isArray(v)) {
            return v
              .map(
                (val) => `${encodeURIComponent(k)}=${encodeURIComponent(val)}`,
              )
              .join("&");
          } else {
            return `${encodeURIComponent(k)}=${encodeURIComponent(v)}`;
          }
        })
        .join("&");
      if (query) endpoint += `?${query}`;
    }
    return await this.rawRequest("GET", endpoint, undefined, headers);
  }

  async getContentByType(type: string, lang: string = SEARCH_DATA.RU_LANG) {
    return this.getContent(
      { filter: `contentType:${type}` },
      { [HEADERS.ACCEPT_LANGUAGE]: lang },
    );
  }

  getBanners(lang: string = SEARCH_DATA.RU_LANG) {
    return this.getContentByType(PRODUCT_TYPE.BANNER, lang);
  }

  async getCards(lang: string = SEARCH_DATA.RU_LANG) {
    return this.getContentByType(PRODUCT_TYPE.CARD, lang);
  }

  async getLoans(lang: string = SEARCH_DATA.RU_LANG) {
    return this.getContentByType(PRODUCT_TYPE.LOAN, lang);
  }

  async getDeposits(lang: string = SEARCH_DATA.RU_LANG) {
    return this.getContentByType(PRODUCT_TYPE.DEPOSIT, lang);
  }

  getProductValidationResults(
    properties: any,
    requireExternalId = false,
  ): string[] {
    const checks: Record<string, boolean> = {
      entityTitle:
        typeof properties.entityTitle === DATA_TYPES.STRING &&
        properties.entityTitle.length > 0,
      description:
        typeof properties.description === DATA_TYPES.STRING &&
        properties.description.length > 0,
      url:
        typeof properties.url === DATA_TYPES.STRING &&
        properties.url.length > 0,
      image: Array.isArray(properties.image) && properties.image.length > 0,
    };
    if (requireExternalId) {
      checks.externalId =
        properties.externalId === null ||
        (typeof properties.externalId === DATA_TYPES.STRING &&
          properties.externalId.length > 0);
    }
    const failed = Object.entries(checks)
      .filter(([_, value]) => !value)
      .map(([key]) => key);
    if (failed.length > 0) {
      console.log("Product validation failed for fields:", failed);
    }
    return failed;
  }

  validateItemsProperties(items: any[], requireExternalId = false): string[][] {
    return items.map((item) =>
      this.getProductValidationResults(item.properties, requireExternalId),
    );
  }

  getLocalizationCheckResults(items: any[], regex: RegExp): string[][] {
    return items.map((item) => {
      const failed: string[] = [];
      if (!regex.test(item.properties.entityTitle)) failed.push("entityTitle");
      if (!regex.test(item.properties.description)) failed.push("description");
      return failed;
    });
  }

  checkSortedByName(items: any[]): boolean {
    const names = items.map((i: any) => i.name);
    const sorted = [...names].sort((a, b) =>
      a.localeCompare(b, undefined, { sensitivity: "base" }),
    );
    return names.every((name, idx) => name === sorted[idx]);
  }

  checkSortedByDate(
    items: any[],
    field: string = "createDate",
    order: "desc" | "asc" = "desc",
  ): boolean {
    const dates = items.map((i: any) => new Date(i[field]).getTime());
    const sorted = [...dates].sort((a, b) =>
      order === "desc" ? b - a : a - b,
    );
    return dates.every((date, idx) => date === sorted[idx]);
  }

  static hasOverlappingIds(items1: any[], items2: any[]): boolean {
    const ids1 = new Set(items1.map((item: any) => item.id));
    return items2.some((item: any) => ids1.has(item.id));
  }
}
