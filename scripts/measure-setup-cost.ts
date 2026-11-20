import { UmbracoService } from "../src/services/umbraco.service";
import dotenv from "dotenv";
import path from "path";

dotenv.config({ path: path.resolve(__dirname, "..", process.env.ENV_FILE || ".env") });

async function main() {
  const N = 26;
  let initTotal = 0;
  let disposeTotal = 0;
  let requestTotal = 0;

  for (let i = 0; i < N; i++) {
    const svc = new UmbracoService();

    const t0 = performance.now();
    await svc.init();
    const t1 = performance.now();
    initTotal += t1 - t0;

    const t2 = performance.now();
    await svc.getBanners();
    const t3 = performance.now();
    requestTotal += t3 - t2;

    const t4 = performance.now();
    await svc.dispose();
    const t5 = performance.now();
    disposeTotal += t5 - t4;
  }

  console.log(`N=${N}`);
  console.log(`init() total: ${initTotal.toFixed(1)}ms, avg: ${(initTotal / N).toFixed(2)}ms`);
  console.log(`dispose() total: ${disposeTotal.toFixed(1)}ms, avg: ${(disposeTotal / N).toFixed(2)}ms`);
  console.log(`getBanners() (real HTTP) total: ${requestTotal.toFixed(1)}ms, avg: ${(requestTotal / N).toFixed(2)}ms`);
  console.log(`setup+teardown share of (setup+teardown+request): ${(((initTotal + disposeTotal) / (initTotal + disposeTotal + requestTotal)) * 100).toFixed(1)}%`);
}

main();
