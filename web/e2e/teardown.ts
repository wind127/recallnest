import { request } from "@playwright/test";
// Playwright force-kills web servers on Windows. Remove isolated synthetic data
// while Python is still running, then let Playwright stop both owned processes.
export default async function teardown() {
  const client = await request.newContext();
  try {
    const response = await client.post("http://127.0.0.1:18787/_test/cleanup");
    if (!response.ok() || !(await response.json()).cleaned)
      throw new Error("Synthetic browser database cleanup failed");
  } finally {
    await client.dispose();
  }
}
