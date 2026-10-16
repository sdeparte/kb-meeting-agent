// 48 kHz stereo s16le (what Opus decodes to) -> 16 kHz mono s16le (what Whisper expects):
// average the two channels, then each group of three samples.
export function downsample48kStereoTo16kMono(pcm) {
  const frames = Math.floor(pcm.length / 4);
  const outSamples = Math.floor(frames / 3);
  const out = Buffer.alloc(outSamples * 2);
  for (let i = 0; i < outSamples; i += 1) {
    let sum = 0;
    for (let j = 0; j < 3; j += 1) {
      const offset = (i * 3 + j) * 4;
      sum += pcm.readInt16LE(offset) + pcm.readInt16LE(offset + 2);
    }
    out.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(sum / 6))), i * 2);
  }
  return out;
}
