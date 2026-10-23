// Float samples from the page's AudioContext to the core's 16-bit little-endian PCM.
export function floatToPcm16(samples) {
  const pcm = Buffer.alloc(samples.length * 2);
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    pcm.writeInt16LE(Math.round(clamped * 32767), i * 2);
  }
  return pcm;
}

export function rmsDbfs(samples) {
  let sum = 0;
  for (const sample of samples) sum += sample * sample;
  const rms = Math.sqrt(sum / (samples.length || 1));
  return rms > 0 ? 20 * Math.log10(rms) : -Infinity;
}
