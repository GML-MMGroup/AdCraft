declare module "*?agent-role-retry" {
  const load: () => Promise<import("react").ComponentType<{
    motionState: import("./types.ts").AgentRoleMotionState;
  }>>;
  export default load;
}
