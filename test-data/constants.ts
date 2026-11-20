// Минимальный, вручную извлечённый срез из реального test-data/constants.ts

export enum HttpStatus {
  OK = 200,
  BAD_REQUEST = 400,
  UNAUTHORIZED = 401,
  NOT_FOUND = 404,
}

export const HTTP_MESSAGES: Record<number, string> = {
  [HttpStatus.BAD_REQUEST]: "Bad Request",
};

export const HTTP_METHODS = {
  GET: "get",
  POST: "post",
  PUT: "put",
  DELETE: "delete",
} as const;

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

// --- deposit-calculator.spec.ts (задание 13, продолжение) ---
// Пути банковского API и реальные ID продуктов/валюты каталога — из .env.
export const DEPOSIT_CALCULATOR_ENDPOINT = process.env.DEPOSIT_CALCULATOR_ENDPOINT || "";
export const DEPOSITS_ENDPOINT = process.env.DEPOSITS_ENDPOINT || "";
export const DEPOSIT_TOP_UP_DATE_LIMITS_ENDPOINT =
  process.env.DEPOSIT_TOP_UP_DATE_LIMITS_ENDPOINT || "";

export const DEPOSIT_CALCULATOR_PRODUCTS = {
  NO_TOP_UP: Number(process.env.DEPOSIT_PRODUCT_ID_NO_TOP_UP || 0),
  TERM_NO_REPLENISHMENT: Number(process.env.DEPOSIT_PRODUCT_ID_TERM_NO_REPLENISHMENT || 0),
  KYIAL: Number(process.env.DEPOSIT_PRODUCT_ID_KYIAL || 0),
  NON_EXISTENT: 999999999,
} as const;

export const DEPOSIT_CALCULATOR_CURRENCY_ID = {
  KGS: Number(process.env.DEPOSIT_CURRENCY_ID_KGS || 0),
  NOT_SUPPORTED: 978,
} as const;

export const CURRENCY_CODE = { KGS: "KGS" } as const;

export const DATE_YYYY_MM_DD_REGEX = /^\d{4}-\d{2}-\d{2}$/;

export const DEPOSIT_CALCULATOR_ERRORS = {
  AMOUNT_BELOW_MINIMUM: "DEPOSIT_AMOUNT_BELOW_MINIMUM",
  AMOUNT_BELOW_MINIMUM_MESSAGE_ZERO: "менее 0",
  AMOUNT_ABOVE_MAXIMUM: "DEPOSIT_AMOUNT_ABOVE_MAXIMUM",
  TERM_NOT_AVAILABLE: "DEPOSIT_TERM_NOT_AVAILABLE",
  TERM_NOT_AVAILABLE_MESSAGE: "срок недоступен",
  CURRENCY_NOT_SUPPORTED: "DEPOSIT_CURRENCY_NOT_SUPPORTED",
  CURRENCY_NOT_SUPPORTED_MESSAGE: "валюта недоступна",
  PRODUCT_NOT_FOUND: "DEPOSIT_PRODUCT_NOT_FOUND",
  TOP_UP_NOT_SUPPORTED: "DEPOSIT_TOP_UP_NOT_SUPPORTED",
  TOP_UP_NOT_SUPPORTED_MESSAGE: "недоступно",
  TOP_UP_PARAMETERS_REQUIRED: "DEPOSIT_TOP_UP_PARAMETERS_REQUIRED",
  TOP_UP_PARAMETERS_REQUIRED_MESSAGE: "сумму и дату",
  TOP_UP_AMOUNT_INVALID: "DEPOSIT_TOP_UP_AMOUNT_INVALID",
  TOP_UP_AMOUNT_INVALID_MESSAGE: "больше нуля",
  TOP_UP_DATE_OUT_OF_RANGE: "DEPOSIT_TOP_UP_DATE_OUT_OF_RANGE",
  TOP_UP_DATE_OUT_OF_RANGE_MESSAGE: "пределах",
} as const;

export const DEPOSIT_CALCULATOR_REQUIRED_FIELDS = [
  "product_id",
  "currency_id",
  "amount",
  "term_months",
] as const;

export const DEPOSIT_CALCULATOR_INVALID_TOP_UP_AMOUNTS = [0, -500] as const;

export const LOAN_CALCULATOR_DATA = { INVALID_AMOUNT: "abc" } as const;

export function getRepaymentDayPlusDays(days: number, baseDate?: string): string {
  const date = baseDate ? new Date(baseDate) : new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}
