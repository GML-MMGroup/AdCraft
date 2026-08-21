export class V2ContractValidationError extends Error {
  readonly path: string;
  readonly reason: string;

  constructor(path: string, reason: string) {
    super(`Invalid ${path}: ${reason}`);
    this.name = "V2ContractValidationError";
    this.path = path;
    this.reason = reason;
  }
}

export function isV2ContractValidationError(value: unknown): value is V2ContractValidationError {
  return value instanceof V2ContractValidationError;
}
