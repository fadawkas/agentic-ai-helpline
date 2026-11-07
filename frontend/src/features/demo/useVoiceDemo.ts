import { useEffect, useRef, useState } from "react";

type Phase = "idle" | "connecting" | "connected";
type Session = {
  stopped: boolean;
  context?: AudioContext;
  stream?: MediaStream;
  socket?: WebSocket;
  microphone?: MediaStreamAudioSourceNode;
  worklet?: AudioWorkletNode;
  timer?: ReturnType<typeof setTimeout>;
  sources: Set<AudioBufferSourceNode>;
  nextPlayback: number;
};

function stopPlayback(session: Session) {
  for (const source of session.sources) source.stop();
  session.sources.clear();
  session.nextPlayback = 0;
}

function release(session: Session) {
  session.stopped = true;
  clearTimeout(session.timer);
  session.stream?.getTracks().forEach((track) => track.stop());
  session.microphone?.disconnect();
  session.worklet?.disconnect();
  if (session.worklet) session.worklet.port.onmessage = null;
  stopPlayback(session);
  session.socket?.close();
  if (session.context && session.context.state !== "closed") void session.context.close().catch(() => {});
}

export function useVoiceDemo() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const current = useRef<Session | null>(null);

  useEffect(() => {
    const stop = () => { if (current.current) release(current.current); current.current = null; };
    window.addEventListener("pagehide", stop);
    return () => { window.removeEventListener("pagehide", stop); stop(); };
  }, []);

  const disconnect = () => {
    if (current.current) release(current.current);
    current.current = null;
    setPhase("idle");
    setMessage("Percakapan selesai. Kamu bisa terhubung kembali kapan saja.");
  };

  const connect = async () => {
    if (current.current) return;
    const session: Session = { stopped: false, sources: new Set(), nextPlayback: 0 };
    current.current = session;
    setPhase("connecting");
    setError("");
    setMessage("Izinkan mikrofon, lalu tunggu AI siap.");
    const fail = (text: string) => {
      if (session.stopped) return;
      release(session);
      current.current = null;
      setPhase("idle");
      setMessage("");
      setError(text);
    };
    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        throw new Error("Mikrofon memerlukan koneksi aman. Buka situs melalui tautan HTTPS, lalu coba lagi.");
      }
      session.context = new AudioContext({ sampleRate: 16000 });
      await session.context.resume();
      if (session.stopped) return;
      if (session.context.sampleRate !== 16000) throw new Error("Browser ini belum mendukung percakapan suara. Coba gunakan browser lain.");
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      if (session.stopped) { stream.getTracks().forEach((track) => track.stop()); return; }
      session.stream = stream;
      stream.getAudioTracks()[0]?.addEventListener("ended", () => fail("Mikrofon terputus. Sambungkan kembali lalu coba lagi."));
      await session.context.audioWorklet.addModule("/demo-audio-worklet.js");
      if (session.stopped) return;
      const url = new URL("/api/demo/voice", window.location.href);
      url.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(url);
      socket.binaryType = "arraybuffer";
      session.socket = socket;
      session.timer = setTimeout(() => fail("Koneksi AI terlalu lama. Silakan coba lagi."), 35000);
      socket.onerror = () => fail("Tidak dapat terhubung ke AI. Periksa koneksi lalu coba lagi.");
      socket.onclose = (event) => {
        if (session.stopped) return;
        if (event.code !== 1000) { fail(event.reason || "Layanan suara belum tersedia. Coba lagi nanti."); return; }
        release(session);
        current.current = null;
        setPhase("idle");
        setMessage(event.reason || "Percakapan selesai. Terima kasih sudah berbicara.");
      };
      socket.onmessage = (event: MessageEvent<string | ArrayBuffer>) => {
        if (session.stopped || !session.context) return;
        try {
          if (typeof event.data === "string") {
            const data = JSON.parse(event.data) as { type: string; sample_rate?: number };
            if (data.type === "interruption") { stopPlayback(session); return; }
            if (data.type !== "ready" || session.worklet) return;
            if (data.sample_rate !== 16000) throw new Error("Format audio server tidak sesuai.");
            clearTimeout(session.timer);
            session.microphone = session.context.createMediaStreamSource(stream);
            session.worklet = new AudioWorkletNode(session.context, "demo-microphone");
            session.worklet.port.onmessage = (packet: MessageEvent<ArrayBuffer>) => {
              if (session.stopped || socket.readyState !== WebSocket.OPEN) return;
              if (socket.bufferedAmount > 64000) { fail("Koneksi terlalu lambat untuk audio langsung. Coba lagi."); return; }
              socket.send(packet.data);
            };
            session.microphone.connect(session.worklet);
            session.worklet.connect(session.context.destination);
            setPhase("connected");
            setMessage("AI siap mendengarkan. Mulai bicara dengan nyaman.");
            return;
          }
          if (!event.data.byteLength || event.data.byteLength % 2) return;
          const view = new DataView(event.data);
          const buffer = session.context.createBuffer(1, view.byteLength / 2, 16000);
          const channel = buffer.getChannelData(0);
          for (let i = 0; i < channel.length; i++) channel[i] = view.getInt16(i * 2, true) / 32768;
          if (session.nextPlayback - session.context.currentTime > 2) {
            fail("Pemutaran suara tertunda. Periksa koneksi dan perangkat audio, lalu mulai percakapan baru.");
            return;
          }
          const source = session.context.createBufferSource();
          source.buffer = buffer;
          source.connect(session.context.destination);
          session.sources.add(source);
          source.onended = () => { session.sources.delete(source); source.disconnect(); };
          const start = Math.max(session.context.currentTime + 0.02, session.nextPlayback);
          source.start(start);
          session.nextPlayback = start + buffer.duration;
        } catch {
          fail("Audio tidak dapat diproses. Silakan coba lagi.");
        }
      };
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "NotAllowedError") {
        fail("Akses mikrofon ditolak. Izinkan mikrofon di pengaturan browser, lalu coba lagi.");
      } else if (cause instanceof DOMException && cause.name === "NotFoundError") {
        fail("Mikrofon tidak ditemukan. Sambungkan mikrofon lalu coba lagi.");
      } else {
        fail(cause instanceof Error ? cause.message : "Percakapan belum dapat dimulai. Silakan coba lagi.");
      }
    }
  };

  return { phase, message, error, connect, disconnect };
}
