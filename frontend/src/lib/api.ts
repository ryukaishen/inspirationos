// Typed client for the backend API (reached via the Next.js /api/* proxy).

// CSRF posture (M9): SameSite=Strict cookies plus this required custom
// header on every mutating request — a cross-site form/link can never set
// it, so it's a cheap defense-in-depth check alongside SameSite.
export const CSRF_HEADERS = { "X-Requested-With": "XMLHttpRequest" } as const;

export type ServiceState = "healthy" | "unreachable";

export interface HealthResponse {
  status: "ok" | "degraded";
  db: ServiceState;
  redis: ServiceState;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface JobRead {
  id: number;
  rq_job_id: string | null;
  kind: string;
  status: JobStatus;
  progress: number;
  total: number;
  // IDs/scalars/counts only by construction — the complete-wipe job's
  // verification report (M9) rides here too.
  payload: Record<string, unknown>;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export const FINISHED_JOB_STATUSES: readonly JobStatus[] = ["succeeded", "failed", "cancelled"];

export type ImportStatus =
  | "uploaded"
  | "scanning"
  | "scanned"
  | "extracting"
  | "extracted"
  | "failed"
  | "deleted";

export interface ImportRead {
  id: number;
  source: string;
  filename: string;
  size_bytes: number;
  checksum_sha256: string;
  export_format: "json" | "html_detected";
  status: ImportStatus;
  counts: Record<string, number>;
  error: string | null;
  created_at: string;
}

export interface ImportDetail extends ImportRead {
  latest_job: JobRead | null;
}

export interface UploadAccepted {
  import_id: number;
  job_id: number;
}

// Terminal for the M2 pipeline: polling stops on these.
export const FINISHED_IMPORT_STATUSES: readonly ImportStatus[] = [
  "scanned",
  "extracted",
  "failed",
  "deleted",
];

/** Error carrying the backend's structured `detail` payload (code + message). */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string | null,
    message: string,
    public readonly existingImportId: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function errorFromResponse(response: Response, fallback: string): Promise<ApiError> {
  let code: string | null = null;
  let message = fallback;
  let existingImportId: number | null = null;
  try {
    const body = (await response.json()) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string") {
      message = detail;
    } else if (detail && typeof detail === "object") {
      const d = detail as { code?: string; message?: string; existing_import_id?: number | null };
      code = d.code ?? null;
      message = d.message ?? fallback;
      existingImportId = d.existing_import_id ?? null;
    }
  } catch {
    // non-JSON error body — keep the fallback message
  }
  return new ApiError(response.status, code, message, existingImportId);
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch("/api/health", { cache: "no-store" });
  // 503 carries a valid "degraded" body — only unexpected statuses are errors.
  if (!response.ok && response.status !== 503) {
    throw new Error(`health request failed with status ${response.status}`);
  }
  return (await response.json()) as HealthResponse;
}

// --- auth (M9) ---------------------------------------------------------------

export interface UserRead {
  id: number;
  email: string;
}

export async function login(email: string, password: string): Promise<UserRead> {
  const response = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    throw await errorFromResponse(response, `login failed with status ${response.status}`);
  }
  return (await response.json()) as UserRead;
}

export async function logout(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST", headers: CSRF_HEADERS });
}

export async function getCurrentUser(): Promise<UserRead | null> {
  const response = await fetch("/api/auth/me", { cache: "no-store" });
  if (response.status === 401) return null;
  if (!response.ok) {
    throw new Error(`current-user fetch failed with status ${response.status}`);
  }
  return (await response.json()) as UserRead;
}

export async function enqueueDemoJob(): Promise<JobRead> {
  const response = await fetch("/api/jobs/demo", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify({}),
  });
  if (!response.ok) {
    throw new Error(`demo job enqueue failed with status ${response.status}`);
  }
  return (await response.json()) as JobRead;
}

export async function getJob(jobId: number): Promise<JobRead> {
  const response = await fetch(`/api/jobs/${jobId}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`job fetch failed with status ${response.status}`);
  }
  return (await response.json()) as JobRead;
}

export async function uploadImportZip(file: File): Promise<UploadAccepted> {
  // Raw streamed body (not multipart) so the backend can enforce its size cap
  // before the body is fully read; the filename is display metadata only.
  const params = new URLSearchParams({ filename: file.name });
  const response = await fetch(`/api/imports/upload?${params.toString()}`, {
    method: "POST",
    headers: { "Content-Type": "application/zip", ...CSRF_HEADERS },
    body: file,
  });
  if (!response.ok) {
    throw await errorFromResponse(response, `upload failed with status ${response.status}`);
  }
  return (await response.json()) as UploadAccepted;
}

export async function listImports(): Promise<ImportRead[]> {
  const response = await fetch("/api/imports", { cache: "no-store" });
  if (!response.ok) {
    throw await errorFromResponse(response, `imports fetch failed with status ${response.status}`);
  }
  return (await response.json()) as ImportRead[];
}

export async function getImport(importId: number): Promise<ImportDetail> {
  const response = await fetch(`/api/imports/${importId}`, { cache: "no-store" });
  if (!response.ok) {
    throw await errorFromResponse(response, `import fetch failed with status ${response.status}`);
  }
  return (await response.json()) as ImportDetail;
}

// --- conversations -----------------------------------------------------------

export interface ConversationRead {
  id: number;
  import_id: number;
  thread_path: string;
  title: string | null;
  participant_names: string[];
  message_count: number;
  link_count: number;
  is_self_dm_candidate: boolean;
  is_selected: boolean;
  first_message_at: string | null;
  last_message_at: string | null;
  created_at: string;
}

export interface ExtractAccepted {
  job_id: number;
}

export async function listConversations(importId: number): Promise<ConversationRead[]> {
  const response = await fetch(`/api/imports/${importId}/conversations`, { cache: "no-store" });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `conversations fetch failed with status ${response.status}`,
    );
  }
  return (await response.json()) as ConversationRead[];
}

export async function selectConversations(
  importId: number,
  conversationIds: number[],
): Promise<ExtractAccepted> {
  const response = await fetch(`/api/imports/${importId}/conversations/selection`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify({ conversation_ids: conversationIds }),
  });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `conversation selection failed with status ${response.status}`,
    );
  }
  return (await response.json()) as ExtractAccepted;
}

// --- items ---------------------------------------------------------------------

export type ItemType = "reel" | "post" | "tv" | "story" | "external" | "unknown";
export type ItemStatus = "new" | "needs_context" | "reviewed" | "archived" | "ignored";

export const ITEM_TYPES: readonly ItemType[] = [
  "reel",
  "post",
  "tv",
  "story",
  "external",
  "unknown",
];
export const ITEM_STATUSES: readonly ItemStatus[] = [
  "new",
  "needs_context",
  "reviewed",
  "archived",
  "ignored",
];

export type EnrichmentSource = "oembed" | "og";

export interface ItemRead {
  id: number;
  source: string;
  import_id: number | null;
  conversation_id: number | null;
  message_id: number | null;
  url_raw: string;
  url_canonical: string;
  shortcode: string | null;
  item_type: ItemType;
  shared_at: string | null;
  share_text: string | null;
  adjacent_text: string | null;
  enriched_title: string | null;
  enriched_caption: string | null;
  enriched_author: string | null;
  enriched_source: EnrichmentSource | null;
  context_note: string | null;
  status: ItemStatus;
  tags: string[];
  duplicate_group_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface ItemEntry {
  item: ItemRead;
  duplicate_count: number;
}

export interface ItemsPage {
  entries: ItemEntry[];
  total: number;
  page: number;
  page_size: number;
}

export type ItemsOrder = "default" | "needs_context_first";

export interface ItemsListParams {
  page?: number;
  page_size?: number;
  status?: ItemStatus[];
  item_type?: ItemType[];
  tags?: string[];
  conversation_id?: number;
  date_from?: string;
  date_to?: string;
  search?: string;
  order?: ItemsOrder;
}

export interface ConversationFacet {
  id: number;
  title: string | null;
  item_count: number;
}

export interface TagFacet {
  tag: string;
  item_count: number;
}

export interface ItemFacets {
  conversations: ConversationFacet[];
  tags: TagFacet[];
}

export interface ItemUpdatePatch {
  status?: ItemStatus;
  tags?: string[];
  context_note?: string;
}

export interface BulkUpdatePayload {
  item_ids: number[];
  status?: ItemStatus;
  add_tags?: string[];
  context_note?: string;
  // Expanded server-side to every member — lets one bulk action cover an
  // entire "shared again" group, not just its canonical (visible) item.
  duplicate_group_ids?: number[];
}

export interface BulkUpdateResult {
  updated: number;
}

export interface EnrichPayload {
  item_ids: number[];
  duplicate_group_ids?: number[];
}

export interface EnrichAccepted {
  job_id: number;
}

function buildItemsQuery(params: ItemsListParams): URLSearchParams {
  const query = new URLSearchParams();
  if (params.page !== undefined) query.set("page", String(params.page));
  if (params.page_size !== undefined) query.set("page_size", String(params.page_size));
  for (const value of params.status ?? []) query.append("status", value);
  for (const value of params.item_type ?? []) query.append("item_type", value);
  for (const value of params.tags ?? []) query.append("tags", value);
  if (params.conversation_id !== undefined) {
    query.set("conversation_id", String(params.conversation_id));
  }
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  if (params.search) query.set("search", params.search);
  if (params.order) query.set("order", params.order);
  return query;
}

export async function listItems(params: ItemsListParams = {}): Promise<ItemsPage> {
  const query = buildItemsQuery(params);
  const response = await fetch(`/api/items?${query.toString()}`, { cache: "no-store" });
  if (!response.ok) {
    throw await errorFromResponse(response, `items fetch failed with status ${response.status}`);
  }
  return (await response.json()) as ItemsPage;
}

export async function getItemFacets(): Promise<ItemFacets> {
  const response = await fetch("/api/items/facets", { cache: "no-store" });
  if (!response.ok) {
    throw await errorFromResponse(response, `facets fetch failed with status ${response.status}`);
  }
  return (await response.json()) as ItemFacets;
}

export async function updateItem(itemId: number, patch: ItemUpdatePatch): Promise<ItemRead> {
  const response = await fetch(`/api/items/${itemId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify(patch),
  });
  if (!response.ok) {
    throw await errorFromResponse(response, `item update failed with status ${response.status}`);
  }
  return (await response.json()) as ItemRead;
}

export async function bulkUpdateItems(payload: BulkUpdatePayload): Promise<BulkUpdateResult> {
  const response = await fetch("/api/items/bulk", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw await errorFromResponse(response, `bulk update failed with status ${response.status}`);
  }
  return (await response.json()) as BulkUpdateResult;
}

export async function enrichItems(payload: EnrichPayload): Promise<EnrichAccepted> {
  const response = await fetch("/api/items/enrich", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw await errorFromResponse(response, `enrich request failed with status ${response.status}`);
  }
  return (await response.json()) as EnrichAccepted;
}

// --- settings --------------------------------------------------------------

export type AiProvider = "anthropic" | "openai" | "mock";

export const AI_PROVIDERS: readonly AiProvider[] = ["anthropic", "openai", "mock"];

export interface SettingsRead {
  enrichment_enabled: boolean;
  enrichment_consent_at: string | null;
  ai_provider: AiProvider;
  // Per-tier model-name overrides for the active provider ("generation"/"fast").
  model_overrides: Record<string, string>;
  monthly_budget_usd: number | null;
  // Scoring-dimension weights (M7); missing dimensions default to 1.0.
  scoring_weights: Record<string, number>;
}

export interface AiSettingsPatch {
  ai_provider?: AiProvider;
  model_overrides?: { generation?: string | null; fast?: string | null } | null;
  monthly_budget_usd?: number | null;
}

export async function getSettings(): Promise<SettingsRead> {
  const response = await fetch("/api/settings", { cache: "no-store" });
  if (!response.ok) {
    throw await errorFromResponse(response, `settings fetch failed with status ${response.status}`);
  }
  return (await response.json()) as SettingsRead;
}

export async function updateEnrichmentSettings(enrichmentEnabled: boolean): Promise<SettingsRead> {
  const response = await fetch("/api/settings/enrichment", {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify({ enrichment_enabled: enrichmentEnabled }),
  });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `settings update failed with status ${response.status}`,
    );
  }
  return (await response.json()) as SettingsRead;
}

export async function updateAiSettings(patch: AiSettingsPatch): Promise<SettingsRead> {
  const response = await fetch("/api/settings/ai", {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify(patch),
  });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `AI settings update failed with status ${response.status}`,
    );
  }
  return (await response.json()) as SettingsRead;
}

// --- analysis & clusters ----------------------------------------------------

export type ClusterRunStatus = "running" | "succeeded" | "failed";

export interface ClusterRead {
  id: number;
  run_id: number;
  label: string | null;
  description_md: string | null;
  size: number;
  topics: string[];
}

export interface ClusterRunRead {
  id: number;
  method: string;
  params: Record<string, unknown>;
  embedding_model: string;
  status: ClusterRunStatus;
  created_at: string;
  cluster_count: number;
}

export interface ClusterRunDetail extends ClusterRunRead {
  clusters: ClusterRead[];
}

export interface AnalysisAccepted {
  job_id: number;
}

async function postAnalysis(path: string, body: unknown): Promise<AnalysisAccepted> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `analysis trigger failed with status ${response.status}`,
    );
  }
  return (await response.json()) as AnalysisAccepted;
}

export async function triggerEmbed(): Promise<AnalysisAccepted> {
  return postAnalysis("/api/analysis/embed", {});
}

export async function triggerCluster(): Promise<AnalysisAccepted> {
  return postAnalysis("/api/analysis/cluster", {});
}

export async function triggerTopics(): Promise<AnalysisAccepted> {
  return postAnalysis("/api/analysis/topics", {});
}

export async function listClusterRuns(): Promise<ClusterRunRead[]> {
  const response = await fetch("/api/cluster-runs", { cache: "no-store" });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `cluster runs fetch failed with status ${response.status}`,
    );
  }
  return (await response.json()) as ClusterRunRead[];
}

export async function getClusterRun(runId: number): Promise<ClusterRunDetail> {
  const response = await fetch(`/api/cluster-runs/${runId}`, { cache: "no-store" });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `cluster run fetch failed with status ${response.status}`,
    );
  }
  return (await response.json()) as ClusterRunDetail;
}

export async function getClusterItems(clusterId: number): Promise<{ items: ItemRead[] }> {
  const response = await fetch(`/api/clusters/${clusterId}/items`, { cache: "no-store" });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `cluster items fetch failed with status ${response.status}`,
    );
  }
  return (await response.json()) as { items: ItemRead[] };
}

export interface ClusterPatch {
  label?: string;
  description_md?: string;
}

export async function updateCluster(clusterId: number, patch: ClusterPatch): Promise<ClusterRead> {
  const response = await fetch(`/api/clusters/${clusterId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify(patch),
  });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `cluster update failed with status ${response.status}`,
    );
  }
  return (await response.json()) as ClusterRead;
}

// --- projects (M7) -----------------------------------------------------------

export type ProjectStatus =
  | "idea"
  | "shortlisted"
  | "planned"
  | "in_progress"
  | "completed"
  | "archived";

export const PROJECT_STATUSES: readonly ProjectStatus[] = [
  "idea",
  "shortlisted",
  "planned",
  "in_progress",
  "completed",
  "archived",
];

export interface SubScore {
  score: number;
  rationale: string;
}

export interface ProjectSource {
  item_ids?: number[];
  cluster_ids?: number[];
  prompt_version?: string;
  provider?: string;
  model?: string;
}

export interface ProjectRead {
  id: number;
  title: string;
  one_liner: string;
  summary_md: string;
  domains: string[];
  difficulty: string | null;
  duration_estimate: string | null;
  datasets: string[];
  tech_stack: string[];
  skills_demonstrated: string[];
  risks: string[];
  // Sub-scores by dimension; the weighted total is computed client-side
  // (lib/scoring.ts) so weight changes re-rank without any API call.
  scores: Record<string, SubScore | undefined>;
  status: ProjectStatus;
  source: ProjectSource;
  parent_project_ids: number[];
  created_at: string;
  updated_at: string;
}

export type MilestoneStatus = "todo" | "doing" | "done";

export const MILESTONE_STATUSES: readonly MilestoneStatus[] = ["todo", "doing", "done"];

export interface MilestoneRead {
  id: number;
  project_id: number;
  title: string;
  description: string | null;
  sort_order: number;
  status: MilestoneStatus;
  target_date: string | null;
}

export interface ProjectDetail extends ProjectRead {
  milestones: MilestoneRead[];
}

export interface ProjectListResponse {
  projects: ProjectRead[];
  total: number;
}

export interface GenerateAccepted {
  job_id: number;
}

export interface GenerateProjectsPayload {
  cluster_ids?: number[];
  item_ids?: number[];
  count?: number;
}

export interface ProjectPatch {
  title?: string;
  one_liner?: string;
  summary_md?: string;
  domains?: string[];
  difficulty?: string | null;
  duration_estimate?: string | null;
  datasets?: string[];
  tech_stack?: string[];
  skills_demonstrated?: string[];
  risks?: string[];
  status?: ProjectStatus;
}

export interface MilestonePayload {
  title: string;
  description?: string | null;
  status?: MilestoneStatus;
  target_date?: string | null;
}

export interface MilestonePatch {
  title?: string;
  description?: string | null;
  status?: MilestoneStatus;
  target_date?: string | null;
}

export interface AdvisorPayload {
  commonality: { verdict: string; reasoning: string };
  comparative_strength: string;
  recruiter_impact: string;
  prerequisites: string[];
  week_by_week: { week: number; focus: string; deliverable: string }[];
}

export interface AdvisorReviewRead {
  id: number;
  project_id: number;
  version: number;
  content_md: string;
  payload: AdvisorPayload | null;
  provider: string;
  model: string;
  prompt_version: string;
  created_at: string;
}

export async function generateProjects(
  payload: GenerateProjectsPayload,
): Promise<GenerateAccepted> {
  const response = await fetch("/api/projects/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `project generation failed with status ${response.status}`,
    );
  }
  return (await response.json()) as GenerateAccepted;
}

export async function combineProjects(
  parentProjectIds: [number, number],
): Promise<GenerateAccepted> {
  const response = await fetch("/api/projects/combine", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify({ parent_project_ids: parentProjectIds }),
  });
  if (!response.ok) {
    throw await errorFromResponse(response, `combine failed with status ${response.status}`);
  }
  return (await response.json()) as GenerateAccepted;
}

export async function listProjects(): Promise<ProjectListResponse> {
  const response = await fetch("/api/projects", { cache: "no-store" });
  if (!response.ok) {
    throw await errorFromResponse(response, `projects fetch failed with status ${response.status}`);
  }
  return (await response.json()) as ProjectListResponse;
}

export async function getProject(projectId: number): Promise<ProjectDetail> {
  const response = await fetch(`/api/projects/${projectId}`, { cache: "no-store" });
  if (!response.ok) {
    throw await errorFromResponse(response, `project fetch failed with status ${response.status}`);
  }
  return (await response.json()) as ProjectDetail;
}

export async function updateProject(projectId: number, patch: ProjectPatch): Promise<ProjectRead> {
  const response = await fetch(`/api/projects/${projectId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify(patch),
  });
  if (!response.ok) {
    throw await errorFromResponse(response, `project update failed with status ${response.status}`);
  }
  return (await response.json()) as ProjectRead;
}

export async function regenerateProject(projectId: number): Promise<GenerateAccepted> {
  const response = await fetch(`/api/projects/${projectId}/regenerate`, {
    method: "POST",
    headers: CSRF_HEADERS,
  });
  if (!response.ok) {
    throw await errorFromResponse(response, `regenerate failed with status ${response.status}`);
  }
  return (await response.json()) as GenerateAccepted;
}

export async function requestAdvisorReview(projectId: number): Promise<GenerateAccepted> {
  const response = await fetch(`/api/projects/${projectId}/advisor`, {
    method: "POST",
    headers: CSRF_HEADERS,
  });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `advisor request failed with status ${response.status}`,
    );
  }
  return (await response.json()) as GenerateAccepted;
}

export async function listAdvisorReviews(projectId: number): Promise<AdvisorReviewRead[]> {
  const response = await fetch(`/api/projects/${projectId}/advisor`, { cache: "no-store" });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `advisor reviews fetch failed with status ${response.status}`,
    );
  }
  return (await response.json()) as AdvisorReviewRead[];
}

export async function createMilestone(
  projectId: number,
  payload: MilestonePayload,
): Promise<MilestoneRead> {
  const response = await fetch(`/api/projects/${projectId}/milestones`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `milestone create failed with status ${response.status}`,
    );
  }
  return (await response.json()) as MilestoneRead;
}

export async function updateMilestone(
  projectId: number,
  milestoneId: number,
  patch: MilestonePatch,
): Promise<MilestoneRead> {
  const response = await fetch(`/api/projects/${projectId}/milestones/${milestoneId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify(patch),
  });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `milestone update failed with status ${response.status}`,
    );
  }
  return (await response.json()) as MilestoneRead;
}

export async function deleteMilestone(projectId: number, milestoneId: number): Promise<void> {
  const response = await fetch(`/api/projects/${projectId}/milestones/${milestoneId}`, {
    method: "DELETE",
    headers: CSRF_HEADERS,
  });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `milestone delete failed with status ${response.status}`,
    );
  }
}

export async function reorderMilestones(
  projectId: number,
  milestoneIds: number[],
): Promise<MilestoneRead[]> {
  const response = await fetch(`/api/projects/${projectId}/milestones/order`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify({ milestone_ids: milestoneIds }),
  });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `milestone reorder failed with status ${response.status}`,
    );
  }
  return (await response.json()) as MilestoneRead[];
}

// --- career artifacts (M8) -----------------------------------------------------

export type CareerArtifactKind =
  | "readme"
  | "resume_bullets"
  | "portfolio_desc"
  | "interview_answer"
  | "tech_questions";

export const CAREER_ARTIFACT_KINDS: readonly CareerArtifactKind[] = [
  "readme",
  "resume_bullets",
  "portfolio_desc",
  "interview_answer",
  "tech_questions",
];

export const CAREER_ARTIFACT_LABELS: Record<CareerArtifactKind, string> = {
  readme: "README",
  resume_bullets: "Resume bullets",
  portfolio_desc: "Portfolio description",
  interview_answer: "Interview answer",
  tech_questions: "Technical questions",
};

export interface ArtifactRead {
  id: number;
  project_id: number;
  kind: CareerArtifactKind | "advisor_review";
  version: number;
  content_md: string;
  payload: Record<string, unknown> | null;
  claims_flags: string[];
  provider: string;
  model: string;
  prompt_version: string;
  created_at: string;
}

export async function requestCareerArtifact(
  projectId: number,
  kind: CareerArtifactKind,
): Promise<GenerateAccepted> {
  const response = await fetch(`/api/projects/${projectId}/artifacts/${kind}`, {
    method: "POST",
    headers: CSRF_HEADERS,
  });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `artifact request failed with status ${response.status}`,
    );
  }
  return (await response.json()) as GenerateAccepted;
}

export async function listCareerArtifacts(
  projectId: number,
  kind: CareerArtifactKind,
): Promise<ArtifactRead[]> {
  const response = await fetch(`/api/projects/${projectId}/artifacts/${kind}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `artifact versions fetch failed with status ${response.status}`,
    );
  }
  return (await response.json()) as ArtifactRead[];
}

export async function listAllArtifacts(projectId: number): Promise<ArtifactRead[]> {
  const response = await fetch(`/api/projects/${projectId}/artifacts`, { cache: "no-store" });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `artifact summary fetch failed with status ${response.status}`,
    );
  }
  return (await response.json()) as ArtifactRead[];
}

// --- export (M8) ---------------------------------------------------------------

export type ExportBundleFormat = "markdown" | "json";

export interface ExportAccepted {
  export_id: number;
  job_id: number;
}

export interface ExportRead {
  id: number;
  project_id: number | null;
  format: ExportBundleFormat;
  ready: boolean;
  size_bytes: number | null;
  error: string | null;
  created_at: string;
}

export async function requestExport(
  format: ExportBundleFormat,
  projectId?: number,
): Promise<ExportAccepted> {
  const response = await fetch("/api/exports", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify({ format, project_id: projectId ?? null }),
  });
  if (!response.ok) {
    throw await errorFromResponse(response, `export request failed with status ${response.status}`);
  }
  return (await response.json()) as ExportAccepted;
}

export async function getExport(exportId: number): Promise<ExportRead> {
  const response = await fetch(`/api/exports/${exportId}`, { cache: "no-store" });
  if (!response.ok) {
    throw await errorFromResponse(response, `export fetch failed with status ${response.status}`);
  }
  return (await response.json()) as ExportRead;
}

export function exportDownloadUrl(exportId: number): string {
  return `/api/exports/${exportId}/download`;
}

// --- career profile (M7) -----------------------------------------------------

export interface CareerProfileRead {
  background_md: string | null;
  skills: string[];
  target_domains: string[];
  experience_level: string | null;
  constraints: Record<string, string>;
  interests_md: string | null;
}

export async function getCareerProfile(): Promise<CareerProfileRead> {
  const response = await fetch("/api/career-profile", { cache: "no-store" });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `career profile fetch failed with status ${response.status}`,
    );
  }
  return (await response.json()) as CareerProfileRead;
}

export async function updateCareerProfile(
  profile: CareerProfileRead,
): Promise<CareerProfileRead> {
  const response = await fetch("/api/career-profile", {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify(profile),
  });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `career profile update failed with status ${response.status}`,
    );
  }
  return (await response.json()) as CareerProfileRead;
}

export async function updateScoringWeights(
  weights: Record<string, number>,
): Promise<SettingsRead> {
  const response = await fetch("/api/settings/scoring", {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify({ scoring_weights: weights }),
  });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `scoring weights update failed with status ${response.status}`,
    );
  }
  return (await response.json()) as SettingsRead;
}

// --- deletion & privacy (M9) --------------------------------------------------

export interface ImportDeletionReport {
  conversations_deleted: number;
  messages_deleted: number;
  items_deleted: number;
  items_kept: number;
  file_deleted: boolean;
}

export async function deleteImport(
  importId: number,
  confirmText: string,
  cascade: boolean,
): Promise<ImportDeletionReport> {
  const response = await fetch(`/api/imports/${importId}/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify({ confirm_text: confirmText, cascade }),
  });
  if (!response.ok) {
    throw await errorFromResponse(response, `import delete failed with status ${response.status}`);
  }
  return (await response.json()) as ImportDeletionReport;
}

export async function deleteProject(projectId: number, confirmText: string): Promise<void> {
  const response = await fetch(`/api/projects/${projectId}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify({ confirm_text: confirmText }),
  });
  if (!response.ok) {
    throw await errorFromResponse(
      response,
      `project delete failed with status ${response.status}`,
    );
  }
}

export interface WipeAccepted {
  job_id: number;
}

export async function requestWipe(confirmEmail: string): Promise<WipeAccepted> {
  const response = await fetch("/api/privacy/wipe", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
    body: JSON.stringify({ confirm_email: confirmEmail }),
  });
  if (!response.ok) {
    throw await errorFromResponse(response, `wipe request failed with status ${response.status}`);
  }
  return (await response.json()) as WipeAccepted;
}
