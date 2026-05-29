/** Engine-layer error carrying a short machine code alongside the message. */
export class EngineError extends Error {
  constructor(
    message: string,
    readonly code: string,
  ) {
    super(message);
    this.name = "EngineError";
  }
}
