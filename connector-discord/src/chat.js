// Which chat lines are commands for the core: "!" lines from people, typed in a voice
// channel's own chat or in the meeting's text channel. Other channels often host other
// bots answering "!" commands (!play, !rank): those lines are not ours.
export function isCommandForCore(message, { guildId, meetingTextChannelId }) {
  const text = message.content?.trim() ?? "";
  if (message.author.bot || message.guildId !== guildId || !text.startsWith("!")) return false;
  return Boolean(message.channel?.isVoiceBased?.()) || message.channelId === meetingTextChannelId;
}
