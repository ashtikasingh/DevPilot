export type QuestionMode = "single-file" | "related-files";

export type RelatedSourceMetadata = {
  source_id: string;
  path: string;
  size_bytes: number;
};

export type RequestIdentity = { current: number };

export function beginRequest(identity: RequestIdentity): number {
  identity.current += 1;
  return identity.current;
}

export function invalidateRequest(identity: RequestIdentity): void {
  identity.current += 1;
}

export function isCurrentRequest(identity: RequestIdentity, requestId: number): boolean {
  return identity.current === requestId;
}

export function getQuestionEndpoint(mode: QuestionMode): string {
  return mode === "related-files"
    ? "/api/repositories/ask-related"
    : "/api/repositories/ask";
}

export function getSourceLabel(source: RelatedSourceMetadata): string {
  return `${source.source_id} · ${source.path}`;
}

export function getContextCoverageMessage(
  complete: boolean,
  message: string | null | undefined,
): string | null {
  if (complete) return null;
  return message || "Some related imports could not be included; the repository was not fully analyzed.";
}
