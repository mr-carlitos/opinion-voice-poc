class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Int16Array(2400);
    this.offset = 0;
  }
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (channel) {
      for (const sample of channel) {
        const value = Math.max(-1, Math.min(1, sample));
        this.buffer[this.offset++] = value < 0 ? value * 32768 : value * 32767;
        if (this.offset === this.buffer.length) {
          this.port.postMessage(this.buffer.buffer);
          this.buffer = new Int16Array(2400);
          this.offset = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor('pcm-capture', PcmCapture);