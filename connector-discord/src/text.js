export const DISCORD_MESSAGE_LIMIT = 2000;

export function truncate(text, limit = DISCORD_MESSAGE_LIMIT) {
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}

// DAVE lifecycle lines only: raw [WS] payloads and state dumps carry session tokens and keys,
// and failed decryptions are counted in the stats rather than logged one by one.
export function isLoggableVoiceDebug(line) {
  return /\[DAVE\]/.test(line) && !/failed to decrypt/i.test(line) && !line.includes("{");
}
