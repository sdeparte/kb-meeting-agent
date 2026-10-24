// Every selector of the Google Meet web client the connector depends on, and nothing else.
// Google changes Meet without notice: when the connector stops joining, hearing speakers or
// reading the chat, this file is the one to fix (docs/manual-test.md has the Meet checklist).
// Written from Meet's accessible names (English and French) and data attributes; not covered
// by the automated tests.
export const SELECTORS = {
  micOff: /^(turn off microphone|désactiver le micro)/i,
  cameraOff: /^(turn off camera|désactiver la caméra)/i,
  joinNow: /^(join now|participer)/i,
  askToJoin: /^(ask to join|demander à participer)/i,
  leaveCall: /^(leave call|quitter l'appel)/i,
  // The lobby already shows the leave button: this text tells it from the call.
  lobby: /(please wait until a meeting host brings you into the call|veuillez patienter jusqu'à ce qu'un organisateur)/i,
  refused: /(you can't join this call|someone in the call denied|vous ne pouvez pas participer|a refusé votre demande)/i,
  ended: /(you left the meeting|the call has ended|you've been removed|vous avez quitté la réunion|l'appel est terminé|vous avez été exclu)/i,
  openChat: /^(chat with everyone|discuter avec tous les participants)/i,
  people: /(show everyone|afficher tous les participants|people|participants)/i,
  chatInput: /^(send a message|envoyer un message)/i,
  tile: "[data-participant-id]",
  tileName: "[data-self-name], span.notranslate",
  // Meet's class names are obfuscated. Seen on 2026-10-23: while someone speaks, BlxGDf is on
  // their tile and the level indicator ([jsname=QgSmzd]) loses gjg47c; silent, the reverse.
  speakingClass: /\bBlxGDf\b/,
  // Only the agent's own tile offers these; it has no data-self-name nor "(you)" any more.
  selfControls: /^(backgrounds and effects|reframe|arrière-plans et effets|recadrer)/i,
  message: "[data-message-id]",
  messageSender: "[data-sender-name]",
  selfNames: ["you", "vous"],
};

export async function isLoggedIn(page) {
  await page.goto("https://meet.google.com/", { waitUntil: "domcontentloaded" }).catch(() => {});
  return !/accounts\.google\.com|workspace\.google\.com/.test(page.url());
}

export async function open(page, url) {
  await page.goto(url, { waitUntil: "domcontentloaded" });
}

// Microphone and camera off on the pre-join screen (the capture also mutes the microphone).
export async function prepare(page) {
  for (const name of [SELECTORS.micOff, SELECTORS.cameraOff]) {
    await page.getByRole("button", { name }).first().click({ timeout: 10_000 }).catch(() => {});
  }
}

export async function askToJoin(page) {
  const now = page.getByRole("button", { name: SELECTORS.joinNow }).first();
  if (await now.isVisible().catch(() => false)) {
    await now.click();
    return "joined";
  }
  await page.getByRole("button", { name: SELECTORS.askToJoin }).first().click({ timeout: 30_000 });
  return "waiting";
}

export async function admitted(page) {
  if (await inMeeting(page)) return "in";
  if (await page.getByText(SELECTORS.refused).first().isVisible().catch(() => false)) return "refused";
  return "waiting";
}

export async function inMeeting(page) {
  if ((await page.getByRole("button", { name: SELECTORS.leaveCall }).count()) === 0) return false;
  return !(await page.getByText(SELECTORS.lobby).first().isVisible().catch(() => false));
}

export async function ended(page) {
  return page.getByText(SELECTORS.ended).first().isVisible().catch(() => false);
}

// Out of the lobby after giving up: no join request left pending.
export async function abandon(page) {
  await page.goto("about:blank").catch(() => {});
}

// The number of people Meet counts in the call (its People button), or null if unknown.
export async function participantCount(page) {
  const label = await page.getByRole("button", { name: SELECTORS.people }).first().getAttribute("aria-label").catch(() => null);
  const count = label?.match(/\d+/);
  return count ? Number(count[0]) : null;
}

export async function leave(page) {
  await page.getByRole("button", { name: SELECTORS.leaveCall }).first().click({ timeout: 10_000 }).catch(() => {});
}

// Participants from the video tiles: Meet's participant id when it has one, else the name.
export async function participants(page) {
  return page.locator(SELECTORS.tile).evaluateAll(
    (tiles, { nameSelector, selfNames, controls }) => {
      const selfControl = new RegExp(controls.source, controls.flags);
      const seen = new Map();
      for (const tile of tiles) {
        const name = (tile.querySelector(nameSelector)?.textContent ?? "").trim();
        const id = tile.getAttribute("data-participant-id") || name;
        if (!id || seen.has(id)) continue;
        const self =
          tile.hasAttribute("data-self-name") ||
          selfNames.some((s) => name.toLowerCase().endsWith(`(${s})`)) ||
          [...tile.querySelectorAll("[aria-label]")].some((el) => selfControl.test(el.getAttribute("aria-label")));
        seen.set(id, { id, name: name.replace(/\s*\((you|vous)\)$/i, ""), self });
      }
      return [...seen.values()];
    },
    {
      nameSelector: SELECTORS.tileName,
      selfNames: SELECTORS.selfNames,
      controls: { source: SELECTORS.selfControls.source, flags: SELECTORS.selfControls.flags },
    },
  );
}

export async function speakers(page) {
  return page.locator(SELECTORS.tile).evaluateAll(
    (tiles, { source, flags }) => {
      const speaking = new RegExp(source, flags);
      const active = (el) => speaking.test(el.className) || [...el.querySelectorAll("*")].some((child) => speaking.test(child.className));
      return [...new Set(tiles.filter(active).map((tile) => tile.getAttribute("data-participant-id")).filter(Boolean))];
    },
    { source: SELECTORS.speakingClass.source, flags: SELECTORS.speakingClass.flags },
  );
}

// The chat panel's button is a toggle: open it only when its input is not there.
async function openChat(page) {
  if ((await page.getByRole("textbox", { name: SELECTORS.chatInput }).count()) > 0) return;
  await page.getByRole("button", { name: SELECTORS.openChat }).first().click({ timeout: 5_000 }).catch(() => {});
}

// The chat messages not read yet.
export async function readChat(page) {
  await openChat(page);
  return page.locator(SELECTORS.message).evaluateAll(
    (messages, { senderSelector, selfNames }) => {
      window.__kbmaSeen ??= new Set();
      const fresh = [];
      for (const message of messages) {
        const id = message.getAttribute("data-message-id");
        if (!id || window.__kbmaSeen.has(id)) continue;
        window.__kbmaSeen.add(id);
        const group = message.closest("[data-sender-name]") ?? message.parentElement;
        const author = (group?.getAttribute("data-sender-name") ?? group?.querySelector(senderSelector)?.textContent ?? "").trim();
        fresh.push({ author, text: message.textContent.trim(), self: selfNames.includes(author.toLowerCase()) });
      }
      return fresh;
    },
    { senderSelector: SELECTORS.messageSender, selfNames: SELECTORS.selfNames },
  );
}

export async function sendChat(page, text) {
  await openChat(page);
  const input = page.getByRole("textbox", { name: SELECTORS.chatInput }).first();
  await input.fill(text);
  await input.press("Enter");
}
