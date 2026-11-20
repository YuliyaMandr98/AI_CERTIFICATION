import { DepositsService } from "../src/services/deposits.service";
import { DEPOSIT_CALCULATOR_PRODUCTS, DEPOSIT_CALCULATOR_CURRENCY_ID } from "../test-data/constants";
import dotenv from "dotenv";
import path from "path";

dotenv.config({ path: path.resolve(__dirname, "..", process.env.ENV_FILE || ".env") });

async function main() {
  const svc = new DepositsService();
  await svc.init();

  const N = 10;
  let conditionsTotal = 0;
  for (let i = 0; i < N; i++) {
    const t0 = performance.now();
    await svc.getProductCurrencyConditions(
      DEPOSIT_CALCULATOR_PRODUCTS.NO_TOP_UP,
      DEPOSIT_CALCULATOR_CURRENCY_ID.KGS as any,
    );
    conditionsTotal += performance.now() - t0;
  }

  let limitsTotal = 0;
  for (let i = 0; i < N; i++) {
    const t0 = performance.now();
    await svc.getDepositTopUpDateLimits();
    limitsTotal += performance.now() - t0;
  }

  await svc.dispose();

  console.log(`getProductCurrencyConditions: avg ${(conditionsTotal / N).toFixed(1)}ms over ${N} calls`);
  console.log(`getDepositTopUpDateLimits: avg ${(limitsTotal / N).toFixed(1)}ms over ${N} calls`);

  // реальная частота повторных вызовов с ОДИНАКОВЫМИ аргументами в файле
  const repeatedConditionsCalls = 15 + 7 + 1; // NO_TOP_UP+KGS x15, KYIAL+KGS x7, TERM_NO_REPLENISHMENT+KGS x1
  const uniqueConditionsCalls = 3; // 3 уникальные пары (product, currency)
  const repeatedLimitsCalls = 6;
  const uniqueLimitsCalls = 1;

  const conditionsAvg = conditionsTotal / N;
  const limitsAvg = limitsTotal / N;

  console.log(`\nПотенциальная экономия при кэшировании на весь файл:`);
  console.log(
    `  getProductCurrencyConditions: ${repeatedConditionsCalls} вызовов -> ${uniqueConditionsCalls} уникальных = экономия ~${(
      (repeatedConditionsCalls - uniqueConditionsCalls) *
      conditionsAvg
    ).toFixed(0)}ms`,
  );
  console.log(
    `  getDepositTopUpDateLimits: ${repeatedLimitsCalls} вызовов -> ${uniqueLimitsCalls} уникальный = экономия ~${(
      (repeatedLimitsCalls - uniqueLimitsCalls) *
      limitsAvg
    ).toFixed(0)}ms`,
  );
}

main();
