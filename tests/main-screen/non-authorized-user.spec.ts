import { test, expect } from "@fixtures/services.fixture";
import { UmbracoService } from "@services/umbraco.service";
import * as allure from "allure-js-commons";
import { EPIC, STORY } from "@test-data/allure-annotations";
import {
  HEADERS,
  HttpStatus,
  LOCATION_FILTERS,
  PRODUCT_TYPE,
  RESPONSE_PROPERTIES,
  SEARCH_DATA,
  UMBRACO_CONTENT_FETCH,
  UMBRACO_DATE_FILTER,
  UMBRACO_ITEM_IDS,
  UMBRACO_PAGINATION,
  UMBRACO_PREVIEW,
  UMBRACO_PRODUCT_PROPERTIES,
  URL_PATTERN,
} from "@test-data/constants";

test.describe("E-3 | Главный Экран", { tag: "@parallel-safe" }, () => {
  test.describe("US-3.1 | Главный Экран для неавторизованных пользователей", () => {
    let umbracoService: UmbracoService;

    test.beforeEach(async () => {
      allure.story(STORY.HOME_SCREEN_NON_AUTHORIZED);
      allure.epic(EPIC.HOME_SCREEN_NON_AUTHORIZED);

      umbracoService = new UmbracoService();
      await umbracoService.init();
    });

    test.afterEach(async () => {
      await umbracoService.dispose();
    });

    test("6687: Получение баннеров", { tag: "@smoke" }, async () => {
      const response = await umbracoService.getBanners();
      expect.soft(response.status).toBe(HttpStatus.OK);
      const errors = umbracoService.validateItemsProperties(
        response.body.items,
      );
      expect.soft(errors.flat()).toHaveLength(0);
    });

    test("6688: Проверка корректности URL баннера", async () => {
      const response = await umbracoService.getBanners();
      expect.soft(response.status).toBe(HttpStatus.OK);
      const items = response.body.items;
      for (const item of items) {
        expect.soft(URL_PATTERN.test(item.properties.url)).toBe(true);
      }
    });

    test("6689: Получение списка кредитов", { tag: "@smoke" }, async () => {
      const response = await umbracoService.getLoans();
      expect.soft(response.status).toBe(HttpStatus.OK);
      const errors = umbracoService.validateItemsProperties(
        response.body.items,
        true,
      );
      expect.soft(errors.flat()).toHaveLength(0);
    });

    test("6690: Получение списка карт", { tag: "@smoke" }, async () => {
      const response = await umbracoService.getCards();
      expect.soft(response.status).toBe(HttpStatus.OK);
      const errors = umbracoService.validateItemsProperties(
        response.body.items,
      );
      expect.soft(errors.flat()).toHaveLength(0);
    });

    test("6691: Получение списка депозитов", { tag: "@smoke" }, async () => {
      const response = await umbracoService.getDeposits();
      expect.soft(response.status).toBe(HttpStatus.OK);
      const errors = umbracoService.validateItemsProperties(
        response.body.items,
      );
      expect.soft(errors.flat()).toHaveLength(0);
    });

    test("6692: Сортировка продуктов по имени", async () => {
      const response = await umbracoService.getContent({
        fetch: UMBRACO_CONTENT_FETCH.PRODUCTS,
        sort: "name:asc",
      });
      expect.soft(response.status).toBe(HttpStatus.OK);
      const items = response.body.items;
      expect.soft(umbracoService.checkSortedByName(items)).toBe(true);
    });

    test("6693: Получение карточки продукта по id", async () => {
      const response = await umbracoService.getItem(UMBRACO_ITEM_IDS.VALID);
      expect.soft(response.status).toBe(HttpStatus.OK);
      const props = response.body.properties;
      const failed = umbracoService.getProductValidationResults(props);
      expect.soft(failed).toHaveLength(0);
    });

    test("6694: Получение карточки продукта по path", async () => {
      const response = await umbracoService.getItem(
        UMBRACO_ITEM_IDS.UMBRACO_ITEM_PATH,
        undefined,
        { "Start-Item": PRODUCT_TYPE.BANNERS },
      );
      expect.soft(response.status).toBe(HttpStatus.OK);
      expect
        .soft(response.body.route.path)
        .toBe(UMBRACO_ITEM_IDS.UMBRACO_ITEM_PATH_FOR_COMPARE);
    });

    test("6695: Локализация RU", async () => {
      const response = await umbracoService.getDeposits();
      expect.soft(response.status).toBe(HttpStatus.OK);
      const localizationErrors = umbracoService.getLocalizationCheckResults(
        response.body.items,
        SEARCH_DATA.RU_REGEX,
      );
      expect.soft(localizationErrors.flat()).toHaveLength(0);
    });

    test("6696: Локализация KY", async () => {
      const response = await umbracoService.getDeposits(SEARCH_DATA.KY_LANG);
      expect.soft(response.status).toBe(HttpStatus.OK);
      const items = response.body.items;
      const localizationErrors = umbracoService.getLocalizationCheckResults(
        items,
        SEARCH_DATA.KY_REGEX,
      );
      expect.soft(localizationErrors.flat()).toHaveLength(0);
    });

    test("6697: Локализация EN", async () => {
      const response = await umbracoService.getDeposits(SEARCH_DATA.EN_LANG);
      expect.soft(response.status).toBe(HttpStatus.OK);
      const localizationErrors = umbracoService.getLocalizationCheckResults(
        response.body.items,
        SEARCH_DATA.EN_REGEX,
      );
      expect.soft(localizationErrors.flat()).toHaveLength(0);
    });

    test("6698: Ошибка — элемент не найден", async () => {
      const response = await umbracoService.getItem(UMBRACO_ITEM_IDS.INVALID);
      expect.soft(response.status).toBe(HttpStatus.NOT_FOUND);
    });

    test("6684: Некорректный contentType/filter", async () => {
      const response = await umbracoService.getContentByType(
        PRODUCT_TYPE.UNKNOWN,
        SEARCH_DATA.EN_LANG,
      );
      expect.soft(response.status).toBe(HttpStatus.OK);
      expect.soft(response.body.items.length).toBe(0);
    });

    test("6685: Некорректный path", async () => {
      const response = await umbracoService.getItem(
        UMBRACO_ITEM_IDS.INVALID_PATH,
        undefined,
        { "Start-Item": PRODUCT_TYPE.BANNER },
      );
      expect.soft(response.status).toBe(HttpStatus.NOT_FOUND);
    });

    test("6686: Неверный Accept-Language", async () => {
      const response = await umbracoService.getDeposits(
        SEARCH_DATA.NON_EXISTING_LANG,
      );
      expect.soft(response.status).toBe(HttpStatus.OK);
      expect.soft(response.body.items.length).toBe(0);
    });

    test("6662: Получение элемента по id: параметр fields ограничивает набор properties", async () => {
      const response = await umbracoService.getItem(
        UMBRACO_ITEM_IDS.VALID,
        `fields=properties[${UMBRACO_PRODUCT_PROPERTIES.join(",")}]`,
      );

      expect.soft(response.status).toBe(HttpStatus.OK);
      expect.soft(response.body).toHaveProperty(RESPONSE_PROPERTIES.PROPERTIES);
      const properties = response.body.properties;
      // Проверяем, что в properties есть только поля из fields
      expect
        .soft(Object.keys(properties).sort())
        .toEqual(UMBRACO_PRODUCT_PROPERTIES.sort());
    });

    test("6664: Получение элемента по id: локализация через Accept-Language", async () => {
      const response = await umbracoService.getItem(
        UMBRACO_ITEM_IDS.VALID,
        undefined,
        { [HEADERS.ACCEPT_LANGUAGE]: SEARCH_DATA.EN_LANG },
      );
      expect.soft(response.status).toBe(HttpStatus.OK);
      expect.soft(response.body.cultures).toBeDefined();
    });

    test("6675: Фильтрация: filter=contentType:alias ограничивает результаты", async () => {
      const response = await umbracoService.getContent({
        fetch: UMBRACO_CONTENT_FETCH.PRODUCTS,
        filter: `contentType:${PRODUCT_TYPE.LOAN}`,
      });
      expect.soft(response.status).toBe(HttpStatus.OK);
      expect
        .soft(
          response.body.items.every(
            (item: any) => item.contentType === PRODUCT_TYPE.LOAN,
          ),
        )
        .toBe(true);
    });

    test("6677: Множественные фильтры: элемент должен соответствовать всем filter", async () => {
      const response = await umbracoService.getContent({
        fetch: UMBRACO_CONTENT_FETCH.PRODUCTS,
        filter: [
          `contentType:${PRODUCT_TYPE.LOAN}`,
          `name:${LOCATION_FILTERS.OVERDRAFT}`,
        ],
      });
      expect.soft(response.status).toBe(HttpStatus.OK);
      expect
        .soft(
          response.body.items.every(
            (item: any) =>
              item.contentType === PRODUCT_TYPE.LOAN &&
              item.name === LOCATION_FILTERS.OVERDRAFT,
          ),
        )
        .toBe(true);
    });

    test("6678: Сортировка: sort=createDate:desc возвращает элементы в убывающем порядке", async () => {
      const response = await umbracoService.getContent({
        fetch: UMBRACO_CONTENT_FETCH.PRODUCTS,
        sort: "createDate:desc",
      });
      expect.soft(response.status).toBe(HttpStatus.OK);
      expect
        .soft(
          umbracoService.checkSortedByDate(
            response.body.items,
            "createDate",
            "desc",
          ),
        )
        .toBe(true);
    });

    test("19648: Fetch=children возвращает дочерние элементы узла", async () => {
      const response = await umbracoService.getContent({
        fetch: UMBRACO_CONTENT_FETCH.PRODUCTS_CHILDREN,
      });
      expect.soft(response.status).toBe(HttpStatus.OK);
      expect.soft(response.body.total).toBeGreaterThan(0);
      const validTypes: string[] = [
        PRODUCT_TYPE.CARD,
        PRODUCT_TYPE.LOAN,
        PRODUCT_TYPE.DEPOSIT,
      ];
      expect
        .soft(
          response.body.items.every((item: any) =>
            validTypes.includes(item.contentType),
          ),
        )
        .toBe(true);
    });

    test("19649: Fetch=ancestors возвращает родительский узел элемента", async () => {
      const response = await umbracoService.getContent({
        fetch: `ancestors:${UMBRACO_ITEM_IDS.VALID}`,
      });
      expect.soft(response.status).toBe(HttpStatus.OK);
      expect.soft(response.body.total).toBe(1);
      expect
        .soft(response.body.items[0]?.contentType)
        .toBe(PRODUCT_TYPE.PRODUCTS_ROOT);
    });

    test("19650: Пагинация: skip и take ограничивают и смещают выборку списка продуктов", async () => {
      const firstPage = await umbracoService.getContent({
        fetch: UMBRACO_CONTENT_FETCH.PRODUCTS,
        take: UMBRACO_PAGINATION.TAKE,
      });
      const secondPage = await umbracoService.getContent({
        fetch: UMBRACO_CONTENT_FETCH.PRODUCTS,
        take: UMBRACO_PAGINATION.TAKE,
        skip: UMBRACO_PAGINATION.SKIP,
      });
      expect(firstPage.status).toBe(HttpStatus.OK);
      expect(secondPage.status).toBe(HttpStatus.OK);
      expect
        .soft(firstPage.body.items.length)
        .toBeLessThanOrEqual(UMBRACO_PAGINATION.TAKE);
      expect
        .soft(secondPage.body.items.length)
        .toBeLessThanOrEqual(UMBRACO_PAGINATION.TAKE);
      expect.soft(secondPage.body.total).toBe(firstPage.body.total);
      expect
        .soft(
          UmbracoService.hasOverlappingIds(
            firstPage.body.items,
            secondPage.body.items,
          ),
        )
        .toBe(false);
    });

    test("19651: Параметр expand не нарушает структуру ответа элемента", async () => {
      const response = await umbracoService.getItem(
        UMBRACO_ITEM_IDS.VALID,
        "expand=properties",
      );
      expect.soft(response.status).toBe(HttpStatus.OK);
      const failed = umbracoService.getProductValidationResults(
        response.body.properties,
      );
      expect.soft(failed).toHaveLength(0);
    });

    test("19652: Фильтрация по диапазону createDate", async () => {
      const currentRange = await umbracoService.getContent({
        fetch: UMBRACO_CONTENT_FETCH.PRODUCTS,
        filter: [
          `createDate>:${UMBRACO_DATE_FILTER.RANGE_START}`,
          `createDate<:${UMBRACO_DATE_FILTER.RANGE_END}`,
        ],
      });
      const futureRange = await umbracoService.getContent({
        fetch: UMBRACO_CONTENT_FETCH.PRODUCTS,
        filter: `createDate>:${UMBRACO_DATE_FILTER.FUTURE_START}`,
      });
      expect.soft(currentRange.status).toBe(HttpStatus.OK);
      expect.soft(futureRange.status).toBe(HttpStatus.OK);
      expect.soft(currentRange.body.items.length).toBeGreaterThan(0);
      expect.soft(futureRange.body.items.length).toBe(0);
    });

    test("19653: Preview без валидного Api-Key — 401 Unauthorized", async () => {
      const response = await umbracoService.getItem(
        UMBRACO_ITEM_IDS.VALID,
        undefined,
        {
          [HEADERS.PREVIEW]: UMBRACO_PREVIEW.ENABLED,
          [HEADERS.API_KEY]: UMBRACO_PREVIEW.INVALID_API_KEY,
        },
      );
      expect.soft(response.status).toBe(HttpStatus.UNAUTHORIZED);
    });
  });
});
