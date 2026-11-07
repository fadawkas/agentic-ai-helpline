// Send 20 ms mono PCM16 packets. Output remains silent (no microphone loopback).
class DemoMicrophone extends AudioWorkletProcessor {
  constructor() {
    super();
    this.packet = new ArrayBuffer(640);
    this.view = new DataView(this.packet);
    this.offset = 0;
  }

  process(inputs) {
    const samples = inputs[0]?.[0];
    if (samples) {
      for (const sample of samples) {
        const clamped = Math.max(-1, Math.min(1, sample));
        this.view.setInt16(this.offset * 2, clamped < 0 ? clamped * 32768 : clamped * 32767, true);
        if (++this.offset === 320) {
          this.port.postMessage(this.packet, [this.packet]);
          this.packet = new ArrayBuffer(640);
          this.view = new DataView(this.packet);
          this.offset = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor("demo-microphone", DemoMicrophone);
