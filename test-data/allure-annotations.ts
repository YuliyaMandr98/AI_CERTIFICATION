// Минимальный срез из реального test-data/allure-annotations.ts

export const EPIC = {
  HOME_SCREEN_NON_AUTHORIZED:
    "EPIC: [E3]: US-3.1 | Home Screen for Non-Authorized User (Pre-Authorization Zone)",
  DEPOSIT_CALCULATOR: "EPIC: [E9]: US-9.2.1 | Депозитный калькулятор",
} as const;

export const STORY = {
  HOME_SCREEN_NON_AUTHORIZED:
    "STORY: [E3]: US-3.1 | Home Screen for Non-Authorized User (Pre-Authorization Zone): Automate API test cases",
  DEPOSIT_CALCULATOR:
    "STORY: [E9]: US-9.2.1 | Депозитный калькулятор: Automate API test cases",
} as const;
