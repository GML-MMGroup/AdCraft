export interface AgentLLMConfig {
	baseUrl: string;
	apiKey: string;
	model: string;
}

export interface AgentToolDefinition {
	name: string;
	description: string;
	parameters: Record<string, unknown>;
	requiresConfirmation?: boolean;
	execute: (args: Record<string, unknown>) => Promise<AgentToolResult>;
}

export interface AgentToolResult {
	success: boolean;
	message: string;
	data?: Record<string, unknown>;
}

export type AgentMessageRole = "system" | "user" | "assistant" | "tool";

export interface AgentToolCall {
	id: string;
	name: string;
	arguments: Record<string, unknown>;
}

export interface AgentToolCallMessage {
	role: "tool";
	toolCallId: string;
	toolName: string;
	content: string;
}

export interface AgentMessage {
	id: string;
	role: AgentMessageRole;
	content: string;
	toolCalls?: AgentToolCall[];
	toolCallId?: string;
	toolName?: string;
	timestamp: number;
}

export type AgentStatus =
	| "idle"
	| "thinking"
	| "executing"
	| "awaiting-confirmation"
	| "error";

export interface PendingToolConfirmationItem {
	toolCallId: string;
	toolName: string;
	arguments: Record<string, unknown>;
	description: string;
}

export interface PendingToolConfirmation {
	toolCalls: PendingToolConfirmationItem[];
}

export interface OpenAIChatMessage {
	role: "system" | "user" | "assistant" | "tool";
	content: string | null;
	tool_calls?: Array<{
		id: string;
		type: "function";
		function: {
			name: string;
			arguments: string;
		};
	}>;
	tool_call_id?: string;
}

export interface OpenAIToolSchema {
	type: "function";
	function: {
		name: string;
		description: string;
		parameters: Record<string, unknown>;
	};
}

export interface OpenAIChatCompletionChunk {
	id: string;
	choices: Array<{
		index: number;
		delta: {
			role?: string;
			content?: string | null;
			tool_calls?: Array<{
				index: number;
				id?: string;
				type?: "function";
				function?: {
					name?: string;
					arguments?: string;
				};
			}>;
		};
		finish_reason: string | null;
	}>;
}
