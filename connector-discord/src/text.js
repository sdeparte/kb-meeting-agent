export const DISCORD_MESSAGE_LIMIT = 2000;

export function truncate(text, limit = DISCORD_MESSAGE_LIMIT) {
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}
