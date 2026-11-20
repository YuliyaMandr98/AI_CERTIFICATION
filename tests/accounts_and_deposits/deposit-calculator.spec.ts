// ОПТИМИЗАЦИЯ (задание 13, продолжение): в оригинале каждый тест заново
// вызывал getProductCurrencyConditions() (в среднем ~2.3с — тянет весь
// каталог депозитных продуктов и фильтрует на клиенте) и/или
// getDepositTopUpDateLimits(), хотя условия продукта и лимиты пополнения не
// меняются в рамках одного прогона. 23 вызова getProductCurrencyConditions
// на 3 уникальные пары (product, currency) и 6 вызовов
// getDepositTopUpDateLimits на 1 уникальный результат — закэшировано один
// раз в beforeAll. См. results/performance-optimization-report.md.
import { test, expect } from "@fixtures/deposits.fixture";
import {
  CURRENCY_CODE,
  DEPOSIT_CALCULATOR_CURRENCY_ID,
  DEPOSIT_CALCULATOR_ERRORS,
  DEPOSIT_CALCULATOR_INVALID_TOP_UP_AMOUNTS,
  DEPOSIT_CALCULATOR_PRODUCTS,
  DEPOSIT_CALCULATOR_REQUIRED_FIELDS,
  HttpStatus,
  LOAN_CALCULATOR_DATA,
  getRepaymentDayPlusDays,
} from "@test-data/constants";
import * as allure from "allure-js-commons";
import { EPIC, STORY } from "@test-data/allure-annotations";
import {
  expectErrorResponse,
  expectGenericBadRequestWithoutErrorCode,
} from "@helpers/test-helpers";
import { DepositsService } from "@services/deposits.service";

test.describe("E-9 | Счета и депозиты", () => {
  test.describe("US-9.2.1 | Депозитный калькулятор", () => {
    let noTopUpConditions: any;
    let kyialConditions: any;
    let termConditions: any;
    let topUpLimits: any;

    test.beforeAll(async () => {
      const svc = new DepositsService();
      await svc.init();
      noTopUpConditions = await svc.getProductCurrencyConditions(
        DEPOSIT_CALCULATOR_PRODUCTS.NO_TOP_UP,
        CURRENCY_CODE.KGS,
      );
      kyialConditions = await svc.getProductCurrencyConditions(
        DEPOSIT_CALCULATOR_PRODUCTS.KYIAL,
        CURRENCY_CODE.KGS,
      );
      termConditions = await svc.getProductCurrencyConditions(
        DEPOSIT_CALCULATOR_PRODUCTS.TERM_NO_REPLENISHMENT,
        CURRENCY_CODE.KGS,
      );
      const { body: limits } = await svc.getDepositTopUpDateLimits();
      topUpLimits = limits;
      await svc.dispose();
    });

    test.beforeEach(() => {
      allure.story(STORY.DEPOSIT_CALCULATOR);
      allure.epic(EPIC.DEPOSIT_CALCULATOR);
    });

    test(
      "25375: Успешный расчёт доходности депозита: структура и типы полей ответа",
      { tag: ["@parallel-safe", "@smoke"] },
      async ({ depositsService }) => {
        const { status, body } = await depositsService.calculateDeposit({
          product_id: DEPOSIT_CALCULATOR_PRODUCTS.NO_TOP_UP,
          currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
          amount: noTopUpConditions.min_amount + 1000,
          term_months: noTopUpConditions.min_term,
          top_up_enabled: false,
          monthly_top_up_amount: null,
          top_up_date: null,
        });

        expect(status).toBe(HttpStatus.OK);
        expect
          .soft(DepositsService.validateCalculateResponseStructure(body))
          .toHaveLength(0);
      },
    );

    test(
      "25376: Бизнес-корректность итоговой суммы: total_amount_at_end = initial_amount + expected_income + bonus_income",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        const { status, body } = await depositsService.calculateDeposit({
          product_id: DEPOSIT_CALCULATOR_PRODUCTS.NO_TOP_UP,
          currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
          amount: noTopUpConditions.min_amount + 1000,
          term_months: noTopUpConditions.min_term,
          top_up_enabled: false,
          monthly_top_up_amount: null,
          top_up_date: null,
        });
        expect.soft(status).toBe(HttpStatus.OK);
        const expectedTotal =
          body.initial_amount + body.expected_income + body.bonus_income;
        expect
          .soft(Math.round(body.total_amount_at_end * 100))
          .toBe(Math.round(expectedTotal * 100));
      },
    );

    test(
      "25377: Граничные значения amount/term_months (min/max включительно) возвращают успешный расчёт",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        const boundaries =
          DepositsService.buildAmountTermBoundaryCases(noTopUpConditions);

        for (const [label, amount, term_months] of boundaries) {
          const { status } = await depositsService.calculateDeposit({
            product_id: DEPOSIT_CALCULATOR_PRODUCTS.NO_TOP_UP,
            currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
            amount,
            term_months,
            top_up_enabled: false,
            monthly_top_up_amount: null,
            top_up_date: null,
          });
          expect.soft(status, label).toBe(HttpStatus.OK);
        }
      },
    );

    test(
      "25378: Продукт с бонусной программой возвращает ненулевые bonus_rate/bonus_income",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        const { status, body } = await depositsService.calculateDeposit({
          product_id: DEPOSIT_CALCULATOR_PRODUCTS.KYIAL,
          currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
          amount: kyialConditions.min_amount + 1000,
          term_months: kyialConditions.min_term,
          top_up_enabled: true,
          monthly_top_up_amount: 1000,
          top_up_date: getRepaymentDayPlusDays(10, topUpLimits.bank_date),
        });

        expect.soft(status).toBe(HttpStatus.OK);
        expect.soft(body.bonus_rate).toBeGreaterThan(0);
        expect.soft(body.bonus_income).toBeGreaterThan(0);
      },
    );

    test(
      "25379: Продукт без бонусной программы возвращает bonus_rate=null и bonus_income=0",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        const { status, body } = await depositsService.calculateDeposit({
          product_id: DEPOSIT_CALCULATOR_PRODUCTS.NO_TOP_UP,
          currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
          amount: noTopUpConditions.min_amount + 1000,
          term_months: noTopUpConditions.min_term,
          top_up_enabled: false,
          monthly_top_up_amount: null,
          top_up_date: null,
        });

        expect.soft(status).toBe(HttpStatus.OK);
        expect.soft(body.bonus_rate).toBeNull();
        expect.soft(body.bonus_income).toBe(0);
      },
    );

    test(
      "25380: Сумма ниже минимума возвращает 400 DEPOSIT_AMOUNT_BELOW_MINIMUM",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        const { status, response } = await depositsService.calculateDeposit({
          product_id: DEPOSIT_CALCULATOR_PRODUCTS.NO_TOP_UP,
          currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
          amount: noTopUpConditions.min_amount - 1,
          term_months: noTopUpConditions.min_term,
          top_up_enabled: false,
          monthly_top_up_amount: null,
          top_up_date: null,
        });

        expect(status).toBe(HttpStatus.BAD_REQUEST);
        await expectErrorResponse(
          response,
          DEPOSIT_CALCULATOR_ERRORS.AMOUNT_BELOW_MINIMUM,
          String(noTopUpConditions.min_amount),
        );
      },
    );

    test(
      "25381: Сумма выше максимума возвращает 400 DEPOSIT_AMOUNT_ABOVE_MAXIMUM",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        const { status, response } = await depositsService.calculateDeposit({
          product_id: DEPOSIT_CALCULATOR_PRODUCTS.NO_TOP_UP,
          currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
          amount: noTopUpConditions.max_amount + 1,
          term_months: noTopUpConditions.min_term,
          top_up_enabled: false,
          monthly_top_up_amount: null,
          top_up_date: null,
        });

        expect(status).toBe(HttpStatus.BAD_REQUEST);
        await expectErrorResponse(
          response,
          DEPOSIT_CALCULATOR_ERRORS.AMOUNT_ABOVE_MAXIMUM,
          String(noTopUpConditions.max_amount),
        );
      },
    );

    test(
      "25382: Отрицательная сумма возвращает 400 DEPOSIT_AMOUNT_BELOW_MINIMUM",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        const { status, response } = await depositsService.calculateDeposit({
          product_id: DEPOSIT_CALCULATOR_PRODUCTS.NO_TOP_UP,
          currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
          amount: -1000,
          term_months: noTopUpConditions.min_term,
          top_up_enabled: false,
          monthly_top_up_amount: null,
          top_up_date: null,
        });

        expect(status).toBe(HttpStatus.BAD_REQUEST);
        await expectErrorResponse(
          response,
          DEPOSIT_CALCULATOR_ERRORS.AMOUNT_BELOW_MINIMUM,
          DEPOSIT_CALCULATOR_ERRORS.AMOUNT_BELOW_MINIMUM_MESSAGE_ZERO,
        );
      },
    );

    test(
      "25383: Нечисловая строка в поле amount возвращает 400 без error_code",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        const { response } = await depositsService.calculateDeposit({
          product_id: DEPOSIT_CALCULATOR_PRODUCTS.NO_TOP_UP,
          currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
          amount: LOAN_CALCULATOR_DATA.INVALID_AMOUNT,
          term_months: noTopUpConditions.min_term,
          top_up_enabled: false,
          monthly_top_up_amount: null,
          top_up_date: null,
        });

        await expectGenericBadRequestWithoutErrorCode(response);
      },
    );

    test(
      "25384: Пустое тело запроса возвращает 400 без error_code",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        const { response } = await depositsService.calculateDeposit({});
        await expectGenericBadRequestWithoutErrorCode(response);
      },
    );

    test(
      "25385: Срок ниже минимума возвращает 400 DEPOSIT_TERM_NOT_AVAILABLE",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        const { status, response } = await depositsService.calculateDeposit({
          product_id: DEPOSIT_CALCULATOR_PRODUCTS.NO_TOP_UP,
          currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
          amount: noTopUpConditions.min_amount + 1000,
          term_months: noTopUpConditions.min_term - 1,
          top_up_enabled: false,
          monthly_top_up_amount: null,
          top_up_date: null,
        });

        expect(status).toBe(HttpStatus.BAD_REQUEST);
        await expectErrorResponse(
          response,
          DEPOSIT_CALCULATOR_ERRORS.TERM_NOT_AVAILABLE,
          DEPOSIT_CALCULATOR_ERRORS.TERM_NOT_AVAILABLE_MESSAGE,
        );
      },
    );

    test(
      "25386: Срок выше максимума возвращает 400 DEPOSIT_TERM_NOT_AVAILABLE",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        const { status, response } = await depositsService.calculateDeposit({
          product_id: DEPOSIT_CALCULATOR_PRODUCTS.NO_TOP_UP,
          currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
          amount: noTopUpConditions.min_amount + 1000,
          term_months: noTopUpConditions.max_term + 1,
          top_up_enabled: false,
          monthly_top_up_amount: null,
          top_up_date: null,
        });

        expect(status).toBe(HttpStatus.BAD_REQUEST);
        await expectErrorResponse(
          response,
          DEPOSIT_CALCULATOR_ERRORS.TERM_NOT_AVAILABLE,
        );
      },
    );

    test(
      "25387: Нулевой и отрицательный срок возвращают 400 DEPOSIT_TERM_NOT_AVAILABLE",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        for (const term_months of [0, -1]) {
          const { status, response } = await depositsService.calculateDeposit({
            product_id: DEPOSIT_CALCULATOR_PRODUCTS.NO_TOP_UP,
            currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
            amount: noTopUpConditions.min_amount + 1000,
            term_months,
            top_up_enabled: false,
            monthly_top_up_amount: null,
            top_up_date: null,
          });
          expect
            .soft(status, `term_months=${term_months}`)
            .toBe(HttpStatus.BAD_REQUEST);
          await expectErrorResponse(
            response,
            DEPOSIT_CALCULATOR_ERRORS.TERM_NOT_AVAILABLE,
          );
        }
      },
    );

    test(
      "25388: Валюта, не поддерживаемая продуктом, возвращает 400 DEPOSIT_CURRENCY_NOT_SUPPORTED",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        const { status, response } = await depositsService.calculateDeposit({
          product_id: DEPOSIT_CALCULATOR_PRODUCTS.NO_TOP_UP,
          currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.NOT_SUPPORTED,
          amount: noTopUpConditions.min_amount + 1000,
          term_months: noTopUpConditions.min_term,
          top_up_enabled: false,
          monthly_top_up_amount: null,
          top_up_date: null,
        });

        expect(status).toBe(HttpStatus.BAD_REQUEST);
        await expectErrorResponse(
          response,
          DEPOSIT_CALCULATOR_ERRORS.CURRENCY_NOT_SUPPORTED,
          DEPOSIT_CALCULATOR_ERRORS.CURRENCY_NOT_SUPPORTED_MESSAGE,
        );
      },
    );

    test(
      "25389: Несуществующий product_id возвращает 404 DEPOSIT_PRODUCT_NOT_FOUND",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        const { status, response } = await depositsService.calculateDeposit({
          product_id: DEPOSIT_CALCULATOR_PRODUCTS.NON_EXISTENT,
          currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
          amount: noTopUpConditions.min_amount + 1000,
          term_months: noTopUpConditions.min_term,
          top_up_enabled: false,
          monthly_top_up_amount: null,
          top_up_date: null,
        });

        expect(status).toBe(HttpStatus.NOT_FOUND);
        await expectErrorResponse(
          response,
          DEPOSIT_CALCULATOR_ERRORS.PRODUCT_NOT_FOUND,
        );
      },
    );

    test(
      "25390: Отсутствие каждого из обязательных полей возвращает 400 без error_code",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        const validBody: Record<string, any> = {
          product_id: DEPOSIT_CALCULATOR_PRODUCTS.NO_TOP_UP,
          currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
          amount: noTopUpConditions.min_amount + 1000,
          term_months: noTopUpConditions.min_term,
          top_up_enabled: false,
          monthly_top_up_amount: null,
          top_up_date: null,
        };

        for (const field of DEPOSIT_CALCULATOR_REQUIRED_FIELDS) {
          const { [field]: _omit, ...rest } = validBody;
          const { response } = await depositsService.calculateDeposit(rest);
          await expectGenericBadRequestWithoutErrorCode(response);
        }
      },
    );

    test(
      "25391: Пополнение по графику недоступно для продукта возвращает 400 DEPOSIT_TOP_UP_NOT_SUPPORTED",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        const { status, response } = await depositsService.calculateDeposit({
          product_id: DEPOSIT_CALCULATOR_PRODUCTS.TERM_NO_REPLENISHMENT,
          currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
          amount: termConditions.min_amount + 1000,
          term_months: termConditions.min_term,
          top_up_enabled: true,
          monthly_top_up_amount: 1000,
          top_up_date: getRepaymentDayPlusDays(10, topUpLimits.bank_date),
        });

        expect(status).toBe(HttpStatus.BAD_REQUEST);
        await expectErrorResponse(
          response,
          DEPOSIT_CALCULATOR_ERRORS.TOP_UP_NOT_SUPPORTED,
          DEPOSIT_CALCULATOR_ERRORS.TOP_UP_NOT_SUPPORTED_MESSAGE,
        );
      },
    );

    test(
      "25392: Не указаны параметры пополнения возвращает 400 DEPOSIT_TOP_UP_PARAMETERS_REQUIRED",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        const { status, response } = await depositsService.calculateDeposit({
          product_id: DEPOSIT_CALCULATOR_PRODUCTS.KYIAL,
          currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
          amount: kyialConditions.min_amount + 1000,
          term_months: kyialConditions.min_term,
          top_up_enabled: true,
          monthly_top_up_amount: null,
          top_up_date: null,
        });

        expect(status).toBe(HttpStatus.BAD_REQUEST);
        await expectErrorResponse(
          response,
          DEPOSIT_CALCULATOR_ERRORS.TOP_UP_PARAMETERS_REQUIRED,
          DEPOSIT_CALCULATOR_ERRORS.TOP_UP_PARAMETERS_REQUIRED_MESSAGE,
        );
      },
    );

    test(
      "25393: Некорректная сумма пополнения возвращает 400 DEPOSIT_TOP_UP_AMOUNT_INVALID",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        for (const monthly_top_up_amount of DEPOSIT_CALCULATOR_INVALID_TOP_UP_AMOUNTS) {
          const { status, response } = await depositsService.calculateDeposit({
            product_id: DEPOSIT_CALCULATOR_PRODUCTS.KYIAL,
            currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
            amount: kyialConditions.min_amount + 1000,
            term_months: kyialConditions.min_term,
            top_up_enabled: true,
            monthly_top_up_amount,
            top_up_date: getRepaymentDayPlusDays(10, topUpLimits.bank_date),
          });
          expect
            .soft(status, `monthly_top_up_amount=${monthly_top_up_amount}`)
            .toBe(HttpStatus.BAD_REQUEST);
          await expectErrorResponse(
            response,
            DEPOSIT_CALCULATOR_ERRORS.TOP_UP_AMOUNT_INVALID,
            DEPOSIT_CALCULATOR_ERRORS.TOP_UP_AMOUNT_INVALID_MESSAGE,
          );
        }
      },
    );

    test(
      "25394: Дата пополнения в будущем вне диапазона возвращает 400 DEPOSIT_TOP_UP_DATE_OUT_OF_RANGE",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        const { status, response } = await depositsService.calculateDeposit({
          product_id: DEPOSIT_CALCULATOR_PRODUCTS.KYIAL,
          currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
          amount: kyialConditions.min_amount + 1000,
          term_months: kyialConditions.min_term,
          top_up_enabled: true,
          monthly_top_up_amount: 1000,
          top_up_date: getRepaymentDayPlusDays(31, topUpLimits.bank_date),
        });

        expect(status).toBe(HttpStatus.BAD_REQUEST);
        await expectErrorResponse(
          response,
          DEPOSIT_CALCULATOR_ERRORS.TOP_UP_DATE_OUT_OF_RANGE,
          DEPOSIT_CALCULATOR_ERRORS.TOP_UP_DATE_OUT_OF_RANGE_MESSAGE,
        );
      },
    );

    test(
      "25395: Дата пополнения в прошлом возвращает 400 DEPOSIT_TOP_UP_DATE_OUT_OF_RANGE",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        const { status, response } = await depositsService.calculateDeposit({
          product_id: DEPOSIT_CALCULATOR_PRODUCTS.KYIAL,
          currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
          amount: kyialConditions.min_amount + 1000,
          term_months: kyialConditions.min_term,
          top_up_enabled: true,
          monthly_top_up_amount: 1000,
          top_up_date: getRepaymentDayPlusDays(-5, topUpLimits.bank_date),
        });

        expect(status).toBe(HttpStatus.BAD_REQUEST);
        await expectErrorResponse(
          response,
          DEPOSIT_CALCULATOR_ERRORS.TOP_UP_DATE_OUT_OF_RANGE,
        );
      },
    );

    test(
      "25396: Валидная дата пополнения возвращает успешный расчёт",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        const { status } = await depositsService.calculateDeposit({
          product_id: DEPOSIT_CALCULATOR_PRODUCTS.KYIAL,
          currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
          amount: kyialConditions.min_amount + 1000,
          term_months: kyialConditions.min_term,
          top_up_enabled: true,
          monthly_top_up_amount: 1000,
          top_up_date: getRepaymentDayPlusDays(10, topUpLimits.bank_date),
        });

        expect(status).toBe(HttpStatus.OK);
      },
    );

    test(
      "25397: top_up_enabled=false для продукта с бонусной программой требует параметры пополнения",
      { tag: "@parallel-safe" },
      async ({ depositsService }) => {
        const { status, body } = await depositsService.calculateDeposit({
          product_id: DEPOSIT_CALCULATOR_PRODUCTS.KYIAL,
          currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
          amount: kyialConditions.min_amount + 1000,
          term_months: kyialConditions.min_term,
          top_up_enabled: false,
          monthly_top_up_amount: null,
          top_up_date: null,
        });

        expect(status).toBe(HttpStatus.BAD_REQUEST);
        expect(body.error_code).toBe(
          DEPOSIT_CALCULATOR_ERRORS.TOP_UP_PARAMETERS_REQUIRED,
        );
      },
    );

    test(
      "25398: Запрос без токена авторизации успешно рассчитывает доходность",
      { tag: ["@parallel-safe", "@smoke"] },
      async ({ depositsService }) => {
        const { status, body } = await depositsService.calculateDeposit({
          product_id: DEPOSIT_CALCULATOR_PRODUCTS.NO_TOP_UP,
          currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
          amount: noTopUpConditions.min_amount + 1000,
          term_months: noTopUpConditions.min_term,
          top_up_enabled: false,
          monthly_top_up_amount: null,
          top_up_date: null,
        });

        expect(status).toBe(HttpStatus.OK);
        expect
          .soft(DepositsService.validateCalculateResponseStructure(body))
          .toHaveLength(0);
      },
    );
  });
});
