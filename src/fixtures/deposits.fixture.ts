// Минимальная локальная фикстура вместо реального @fixtures/services.fixture
// (2013 строк, подключает фикстуры всех сервисов приложения). Здесь — только
// depositsService, который реально используется deposit-calculator.spec.ts.
import { test as base, expect } from "@playwright/test";
import { DepositsService } from "@services/deposits.service";

export const test = base.extend<{ depositsService: DepositsService }>({
  depositsService: async ({}, use) => {
    const svc = new DepositsService();
    await svc.init();
    await use(svc);
    await svc.dispose();
  },
});

export { expect };
