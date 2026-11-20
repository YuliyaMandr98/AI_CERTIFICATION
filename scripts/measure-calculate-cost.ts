import { DepositsService } from "../src/services/deposits.service";
import { DEPOSIT_CALCULATOR_PRODUCTS, DEPOSIT_CALCULATOR_CURRENCY_ID, CURRENCY_CODE } from "../test-data/constants";
import dotenv from "dotenv";
import path from "path";

dotenv.config({ path: path.resolve(__dirname, "..", process.env.ENV_FILE || ".env") });

async function main() {
  const svc = new DepositsService();
  await svc.init();
  const conditions = await svc.getProductCurrencyConditions(
    DEPOSIT_CALCULATOR_PRODUCTS.NO_TOP_UP,
    CURRENCY_CODE.KGS,
  );

  const N = 8;
  let total = 0;
  for (let i = 0; i < N; i++) {
    const t0 = performance.now();
    await svc.calculateDeposit({
      product_id: DEPOSIT_CALCULATOR_PRODUCTS.NO_TOP_UP,
      currency_id: DEPOSIT_CALCULATOR_CURRENCY_ID.KGS,
      amount: conditions.min_amount + 1000,
      term_months: conditions.min_term,
      top_up_enabled: false,
      monthly_top_up_amount: null,
      top_up_date: null,
    });
    total += performance.now() - t0;
  }
  await svc.dispose();
  console.log(`calculateDeposit: avg ${(total / N).toFixed(1)}ms over ${N} calls`);
}

main();
