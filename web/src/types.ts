export type Evidence = {
  message_id: string;
  conversation_id?: string | null;
  message_version?: number | null;
  quote: string;
  stale?: boolean;
};
export type EvidenceInput = Pick<
  Evidence,
  "message_id" | "quote" | "conversation_id" | "message_version"
>;
export type BaseEntity = {
  id: string;
  created_at: string;
  updated_at?: string;
  source?: string;
  evidence: Evidence[];
  project_id?: string | null;
  history?: Record<string, unknown>[];
  source_context?: Record<string, unknown>;
};
export type Knowledge = BaseEntity & {
  title: string;
  summary: string;
  body: string;
  type: string;
  tags: string[];
  favorite: boolean;
  unresolved: boolean;
};
export type Memory = BaseEntity & {
  content: string;
  category: string;
  subject: string;
  status: string;
  effective_at: string;
  expires_at: string | null;
  supersedes: string | null;
};
export type Grade = "again" | "hard" | "good" | "easy";
export type ReviewCard = BaseEntity & {
  question: string;
  answer: string;
  paused: boolean;
  due_at: string;
  knowledge_id?: string | null;
  repetitions?: number;
  interval_minutes?: number;
  grade_history: {
    id: string;
    grade: Grade;
    reviewed_at: string;
    previous_due_at?: string;
    next_due_at: string;
    interval_minutes?: number;
  }[];
};
export type Project = {
  id: string;
  name: string;
  description: string;
  status: string;
  goals: string[];
  artifact_links: { title: string; url: string }[];
  history?: Record<string, unknown>[];
};
export type MessageVersion = {
  version: number;
  role: string;
  content: string;
  timestamp?: string | null;
  raw?: unknown;
  metadata?: unknown;
  recorded_at?: string;
};
export type Message = MessageVersion & {
  id: string;
  conversation_id: string;
  external_id: string;
  parent_id: string | null;
  versions: MessageVersion[];
};
export type Conversation = {
  id: string;
  title: string;
  source: string;
  source_identity: string;
  created_at: string;
  updated_at: string;
  project_id: string | null;
  current_node: string | null;
  revision: number;
  message_count: number;
  messages: Message[];
  branches: { leaf_id: string; external_id: string; message_ids: string[] }[];
  active_message_ids: string[];
  raw_versions?: unknown[];
  metadata?: unknown;
};
export type Job = {
  id: string;
  type: string;
  conversation_id: string;
  status: string;
  attempts: number;
  error: string | null;
  error_kind: string | null;
  disposition: string | null;
  next_attempt_at: string | null;
  result: Record<string, number> | null;
};
export type ProviderSettings = {
  base_url: string;
  chat_model: string;
  embedding_model: string;
  has_api_key: boolean;
  model_configured: boolean;
  connection_verified: boolean;
  storage?: string;
};
export type ServiceStatus = {
  model_configured: boolean;
  worker_running: boolean;
  status: string;
  version: string;
};
export type Context = {
  memory_ids: string[];
  knowledge_ids: string[];
  message_ids: string[];
  evidence: Evidence[];
};
export type ChatResult = {
  conversation_id: string;
  client_turn_id: string;
  user_message: Message | null;
  assistant_message: Message | null;
  used_context: Context;
  error_kind: string | null;
  detail: string | null;
};
export type ChatRequest = {
  conversation_id: string | null;
  branch: string | null;
  content: string;
  client_turn_id: string;
};
export type SearchHit = BaseEntity & {
  entity_type: string;
  title: string;
  excerpt: string;
  type: string;
  tags: string[];
  score: number;
};
export type Page =
  | "overview"
  | "knowledge"
  | "conversations"
  | "projects"
  | "review"
  | "memories";
export type Filters = Record<string, string | boolean | undefined>;
