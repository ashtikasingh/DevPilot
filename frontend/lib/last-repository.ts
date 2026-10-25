export const LAST_REPOSITORY_STORAGE_KEY = "devpilot:last-inspected-repository";

export type SavedRepository = { full_name: string };

export type RepositoryStorageRead =
  | { status: "missing" }
  | { status: "valid"; repository: SavedRepository }
  | { status: "invalid" }
  | { status: "unavailable" };

export type RepositoryRequestIdentity = { current: number };

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function isValidFullName(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const parts = value.split("/");
  if (parts.length !== 2) return false;
  const [owner, repository] = parts;
  return /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/.test(owner)
    && /^[A-Za-z0-9_.-]{1,100}$/.test(repository)
    && repository !== "."
    && repository !== "..";
}

export function parseSavedRepository(serialized: string | null): RepositoryStorageRead {
  if (serialized === null) return { status: "missing" };
  try {
    const value: unknown = JSON.parse(serialized);
    if (
      typeof value !== "object"
      || value === null
      || Array.isArray(value)
      || Object.keys(value).length !== 1
      || !Object.hasOwn(value, "full_name")
      || !isValidFullName((value as { full_name?: unknown }).full_name)
    ) {
      return { status: "invalid" };
    }
    return { status: "valid", repository: { full_name: (value as SavedRepository).full_name } };
  } catch {
    return { status: "invalid" };
  }
}

export function readLastRepository(storage: StorageLike): RepositoryStorageRead {
  try {
    const result = parseSavedRepository(storage.getItem(LAST_REPOSITORY_STORAGE_KEY));
    if (result.status === "invalid") {
      try {
        storage.removeItem(LAST_REPOSITORY_STORAGE_KEY);
      } catch {
        // Invalid browser state is ignored even when storage cannot be cleared.
      }
    }
    return result;
  } catch {
    return { status: "unavailable" };
  }
}

export function saveLastRepository(fullName: string, storage: StorageLike): boolean {
  if (!isValidFullName(fullName)) return false;
  try {
    storage.setItem(LAST_REPOSITORY_STORAGE_KEY, JSON.stringify({ full_name: fullName }));
    return true;
  } catch {
    return false;
  }
}

export function clearLastRepository(storage: StorageLike): boolean {
  try {
    storage.removeItem(LAST_REPOSITORY_STORAGE_KEY);
    return true;
  } catch {
    return false;
  }
}

export function beginRepositoryRequest(identity: RepositoryRequestIdentity): number {
  identity.current += 1;
  return identity.current;
}

export function invalidateRepositoryRequest(identity: RepositoryRequestIdentity): void {
  identity.current += 1;
}

export function isCurrentRepositoryRequest(
  identity: RepositoryRequestIdentity,
  requestId: number,
): boolean {
  return identity.current === requestId;
}
