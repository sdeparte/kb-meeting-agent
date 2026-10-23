// Runs inside the meeting page, before its own scripts. Every remote audio track the page
// receives over WebRTC joins one mix in an AudioContext at 16 kHz (the browser resamples),
// and 20 ms blocks go to Node through the exposed `__kbmaAudio` binding. The tap is a
// ScriptProcessorNode, not an AudioWorklet: a worklet is a module script (blob: URL) that the
// page's Content-Security-Policy may forbid, and the CSP stays enforced.
// The agent's own microphone tracks are disabled, however the page obtains or sends them
// (getUserMedia, addTrack, addTransceiver, replaceTrack): it never sends sound into the call.
export const CAPTURE_SCRIPT = `(() => {
  // WebRTC media capture exists only in secure contexts (https, localhost): elsewhere, leave
  // the page alone.
  if (window.__kbmaCapture || !window.isSecureContext || !window.RTCPeerConnection) return;
  window.__kbmaCapture = true;
  const context = new AudioContext({ sampleRate: 16000 });
  const mix = context.createGain();
  const tap = context.createScriptProcessor(1024, 1, 1);
  const block = new Float32Array(320);
  let filled = 0;
  tap.onaudioprocess = (event) => {
    const input = event.inputBuffer.getChannelData(0);
    for (let i = 0; i < input.length; i++) {
      block[filled++] = input[i];
      if (filled === block.length) {
        window.__kbmaAudio(Array.from(block), Date.now());
        filled = 0;
      }
    }
  };
  const silent = context.createGain();
  silent.gain.value = 0; // the tap must be pulled by the destination, without being heard
  mix.connect(tap);
  tap.connect(silent);
  silent.connect(context.destination);
  // Disabled for good: the page may switch it back on (its own mute button), and that switch
  // does nothing, without throwing. A clone gets the flag back, but the fake microphone only
  // ever plays silence (browser.js).
  const muted = new WeakSet();
  const mute = (track) => {
    if (track && track.kind === "audio" && !muted.has(track)) {
      track.enabled = false;
      Object.defineProperty(track, "enabled", { get: () => false, set() {} });
      muted.add(track);
    }
    return track;
  };
  const getUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia = async (constraints) => {
    const stream = await getUserMedia(constraints);
    stream.getAudioTracks().forEach(mute);
    return stream;
  };
  const replaceTrack = RTCRtpSender.prototype.replaceTrack;
  RTCRtpSender.prototype.replaceTrack = function (track) {
    return replaceTrack.call(this, mute(track));
  };
  const Native = window.RTCPeerConnection;
  window.__kbmaNativeRTCPeerConnection = Native; // what the agent's own tracks are not muted by
  function Wrapped(...args) {
    const connection = new Native(...args);
    connection.addEventListener("track", (event) => {
      if (event.track.kind !== "audio") return;
      const stream = new MediaStream([event.track]);
      // Chromium delivers a remote WebRTC track to Web Audio only while a media element plays it.
      const element = new Audio();
      element.muted = true;
      element.srcObject = stream;
      element.play().catch(() => {});
      try {
        context.resume();
        context.createMediaStreamSource(stream).connect(mix);
      } catch (error) {
        console.error("kbma: audio capture failed: " + error);
      }
    });
    const addTrack = connection.addTrack.bind(connection);
    connection.addTrack = (track, ...streams) => addTrack(mute(track), ...streams);
    const addTransceiver = connection.addTransceiver.bind(connection);
    connection.addTransceiver = (trackOrKind, init) =>
      addTransceiver(typeof trackOrKind === "string" ? trackOrKind : mute(trackOrKind), init);
    return connection;
  }
  Wrapped.prototype = Native.prototype;
  Object.setPrototypeOf(Wrapped, Native);
  window.RTCPeerConnection = Wrapped;
})();`;
