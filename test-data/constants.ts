// Минимальный, вручную извлечённый срез из реального test-data/constants.ts

export enum HttpStatus {
  OK = 200,
  NOT_FOUND = 404,
  UNAUTHORIZED = 401,
}

export const HEADERS = {
  ACCEPT_LANGUAGE: "Accept-Language",
  PREVIEW: "Preview",
  API_KEY: "Api-Key",
} as const;

export const RESPONSE_PROPERTIES = {
  PROPERTIES: "properties",
} as const;

export const DATA_TYPES = {
  STRING: "string",
  NUMBER: "number",
  OBJECT: "object",
  BOOLEAN: "boolean",
} as const;

export const SEARCH_DATA = {
  RU_LANG: "ru-RU",
  EN_LANG: "en-US",
  KY_LANG: "ky-KG",
  NON_EXISTING_LANG: "xx-XX",
  RU_REGEX: /[а-яА-ЯёЁ]/,
  EN_REGEX: /[a-zA-Z]/,
  KY_REGEX: /[Ѐ-ӿ]/,
} as const;

export const PRODUCT_TYPE = {
  DEPOSIT: "deposit",
  LOAN: "loan",
  CARD: "card",
  BANNER: "banner",
  BANNERS: "bannery",
  UNKNOWN: "unknown",
  PRODUCTS_ROOT: "products",
} as const;

export const LOCATION_FILTERS = {
  OVERDRAFT: "Overdraft",
} as const;

export const URL_PATTERN = /^https?:\/\//;

// Пути Umbraco Delivery API и реальный ID/путь конкретного элемента CMS
export const UMBRACO_ITEM_ENDPOINT = process.env.UMBRACO_ITEM_ENDPOINT || "";
export const UMBRACO_CONTENT_ENDPOINT = process.env.UMBRACO_CONTENT_ENDPOINT || "";

const validItemPath = process.env.UMBRACO_VALID_ITEM_PATH || "";

export const UMBRACO_ITEM_IDS = {
  VALID: process.env.UMBRACO_VALID_ITEM_ID || "",
  INVALID: "00000000-0000-0000-0000-000000000000",
  INVALID_PATH: "invalid-path-123",
  UMBRACO_ITEM_PATH: validItemPath,
  UMBRACO_ITEM_PATH_FOR_COMPARE: validItemPath ? `/${validItemPath}` : "",
} as const;

export const UMBRACO_CONTENT_FETCH = {
  PRODUCTS: "descendants:/products",
  PRODUCTS_CHILDREN: "children:/products",
} as const;

export const UMBRACO_DATE_FILTER = {
  RANGE_START: "2020-01-01",
  RANGE_END: "2030-01-01",
  FUTURE_START: "2099-01-01",
} as const;

export const UMBRACO_PREVIEW = {
  ENABLED: "true",
  INVALID_API_KEY: "invalid-api-key-12345",
} as const;

export const UMBRACO_PAGINATION = {
  TAKE: 3,
  SKIP: 3,
} as const;

export const UMBRACO_PRODUCT_PROPERTIES = ["entityTitle", "description"];

export const ACCEPT_LANGUAGE_HEADER = {
  RU: { "Accept-Language": "ru-RU" },
} as const;
