import type { Evidence, EvidenceInput } from "./types";
// Output metadata is deliberately excluded; a historical citation keeps its
// exact internal identity, quote and pinned version when an entity is edited.
export function evidenceInput(evidence: Evidence): EvidenceInput {
  return {
    message_id: evidence.message_id,
    quote: evidence.quote,
    ...(evidence.conversation_id !== undefined
      ? { conversation_id: evidence.conversation_id }
      : {}),
    ...(evidence.message_version !== undefined
      ? { message_version: evidence.message_version }
      : {}),
  };
}
