// `npm run login`: open the agent's browser profile, visible, on the workspace, so that you can
// sign in to the agent's dedicated Slack account once. Close the window when Slack is open.
import { openBrowser } from "kbma-browser/browser";

const { SLACK_WORKSPACE_URL, SLACK_BROWSER_PROFILE } = process.env;
if (!SLACK_WORKSPACE_URL || !SLACK_BROWSER_PROFILE) {
  console.error("set SLACK_WORKSPACE_URL and SLACK_BROWSER_PROFILE (the same values as in config.yml)");
  process.exit(2);
}
const { context, page } = await openBrowser({ profileDir: SLACK_BROWSER_PROFILE, headless: false });
await page.goto(SLACK_WORKSPACE_URL);
console.error("Sign in to the agent's Slack account in the window, then close it.");
await new Promise((resolve) => context.on("close", resolve));
