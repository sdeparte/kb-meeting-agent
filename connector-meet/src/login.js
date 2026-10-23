// `npm run login`: open the agent's browser profile, visible, so that you can sign in to the
// agent's dedicated Google account once. Close the window when you are signed in.
import { openBrowser } from "kbma-browser/browser";

const { MEET_BROWSER_PROFILE } = process.env;
if (!MEET_BROWSER_PROFILE) {
  console.error("set MEET_BROWSER_PROFILE (the same value as in config.yml)");
  process.exit(2);
}
const { context, page } = await openBrowser({ profileDir: MEET_BROWSER_PROFILE, headless: false });
await page.goto("https://accounts.google.com/");
console.error("Sign in to the agent's Google account in the window, then close it.");
await new Promise((resolve) => context.on("close", resolve));
