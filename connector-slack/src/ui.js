// Every selector of the Slack web client the connector depends on, and nothing else. Slack
// changes its web client without notice: when the connector stops seeing invitations or
// speakers, this file is the one to fix (docs/manual-test.md has the Slack checklist).
// These selectors are written from Slack's accessible names and data-qa attributes; they
// are not covered by the automated tests.
export const SELECTORS = {
  // the incoming-huddle prompt shown when someone invites the account
  invite: '[data-qa*="huddle"][role="dialog"], [data-qa*="huddle_incoming"]',
  inviteJoin: /^(join|rejoindre)/i,
  // shown while the account is in a huddle
  inHuddle: '[data-qa*="huddle_sidebar_footer"], [data-qa*="huddle_mini"]',
  leave: /^(leave|quitter)/i,
  // participants tiles of the huddle window; the speaking one carries the speaking state
  participant: '[data-qa*="huddle_participant"]',
  participantUserId: "data-user-id",
  speakingClass: /speaking|active-speaker/i,
};

// Logged in when Slack opens its client (app.slack.com/client/…) instead of a sign-in page.
export async function isLoggedIn(page) {
  await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});
  return /\/client\//.test(page.url());
}

export async function waitForInvite(page) {
  await page.locator(SELECTORS.invite).first().waitFor({ state: "visible", timeout: 0 });
  return {};
}

export async function join(page) {
  const prompt = page.locator(SELECTORS.invite).first();
  await prompt.getByRole("button", { name: SELECTORS.inviteJoin }).first().click();
  await page.locator(SELECTORS.inHuddle).first().waitFor({ state: "visible", timeout: 30_000 });
}

export async function leave(page) {
  await page.getByRole("button", { name: SELECTORS.leave }).first().click({ timeout: 10_000 }).catch(() => {});
}

export async function inHuddle(page) {
  return (await page.locator(SELECTORS.inHuddle).count()) > 0;
}

// The huddle's participants, the agent's account included.
export async function participants(page) {
  return page.locator(SELECTORS.participant).evaluateAll(
    (tiles, { attribute }) =>
      tiles
        .map((tile) => ({ id: tile.getAttribute(attribute), name: tile.getAttribute("aria-label") || tile.textContent.trim() }))
        .filter((person) => person.id),
    { attribute: SELECTORS.participantUserId },
  );
}

// Slack user ids of the participants shown speaking.
export async function speakers(page) {
  return page.locator(SELECTORS.participant).evaluateAll(
    (tiles, { attribute, speaking }) =>
      tiles
        .filter((tile) => new RegExp(speaking.source, speaking.flags).test(tile.className) || tile.getAttribute("data-speaking") === "true")
        .map((tile) => tile.getAttribute(attribute))
        .filter(Boolean),
    { attribute: SELECTORS.participantUserId, speaking: { source: SELECTORS.speakingClass.source, flags: SELECTORS.speakingClass.flags } },
  );
}
