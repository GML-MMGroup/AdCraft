import { describe, expect, it } from "vitest";
import { operationPresentation, parseRecordedJson, readableInput, statusLabel } from "./callPresentation";

describe("readable recorded content", () => {
  it("separates the actual user request from the typed context without changing the source", () => {
    const original = 'User request:\n做一款滑板广告\n\nValidated typed operation context:\n{"user_input":"做一款滑板广告","recent_messages":[]}';
    expect(readableInput({ user_prompt: original })).toEqual({ message: "做一款滑板广告", context: { user_input: "做一款滑板广告", recent_messages: [] }, original });
  });
  it("preserves an unrecognized or truncated prompt instead of silently dropping context", () => {
    const original = 'User request:\n广告\n\nValidated typed operation context:\n{"truncated":';
    expect(readableInput({ user_prompt: original }).message).toBe(original);
    expect(parseRecordedJson("{broken")).toBe("{broken");
  });
  it("reads fenced JSON without interpreting ordinary text or changing unknown labels", () => {
    expect(parseRecordedJson('```json\n{"assistant_message":"你好"}\n```')).toEqual({ assistant_message: "你好" });
    expect(parseRecordedJson("123")).toBe("123");
    expect(operationPresentation("future_operation").title).toBe("future_operation");
    expect(statusLabel("future_status")).toBe("future_status");
  });
});
