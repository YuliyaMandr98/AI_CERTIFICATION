import { defineConfig } from "@playwright/test";
import dotenv from "dotenv";
import path from "path";
import { ACCEPT_LANGUAGE_HEADER } from "@test-data/constants";

dotenv.config({ path: path.resolve(__dirname, process.env.ENV_FILE || ".env") });

export default defineConfig({
  testDir: "./tests",
  reporter: [["list"]],
  use: {
    baseURL: process.env.BASE_URL!,
    extraHTTPHeaders: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...ACCEPT_LANGUAGE_HEADER.RU,
    },
  },
  timeout: 60000,
  expect: {
    timeout: 10000,
  },
  projects: [
    {
      name: "api-tests-parallel",
      grep: /@parallel-safe/,
      fullyParallel: true,
      workers: 4,
    },
  ],
});
