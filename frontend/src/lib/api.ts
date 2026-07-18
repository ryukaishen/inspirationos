// Typed client for the backend API (reached via the Next.js /api/* proxy).

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

export async function enqueueDemoJob(): Promise<JobRead> {
  const response = await fetch("/api/jobs/demo", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
    headers: { "Content-Type": "application/zip" },
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
    headers: { "Content-Type": "application/json" },
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
    headers: { "Content-Type": "application/json" },
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
    headers: { "Content-Type": "application/json" },
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
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw await errorFromResponse(response, `enrich request failed with status ${response.status}`);
  }
  return (await response.json()) as EnrichAccepted;
}

// --- settings --------------------------------------------------------------

export interface SettingsRead {
  enrichment_enabled: boolean;
  enrichment_consent_at: string | null;
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
    headers: { "Content-Type": "application/json" },
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
