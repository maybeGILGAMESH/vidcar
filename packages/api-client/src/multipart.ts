import type { CompletedPart, UploadSession } from "./index";

export type UploadState = {
  videoId: string;
  uploadId: string;
  fileName: string;
  fileSize: number;
  completedParts: CompletedPart[];
};

export type UploadStateStore = {
  load(key: string): Promise<UploadState | null>;
  save(key: string, state: UploadState): Promise<void>;
  remove(key: string): Promise<void>;
};

export type UploadSource = {
  name: string;
  size: number;
  contentType: string;
  slice(start: number, end: number): Blob;
};

export const uploadStateKey = (source: Pick<UploadSource, "name" | "size">) =>
  `vidcar-upload:${source.name}:${source.size}`;

export async function uploadMultipart(
  source: UploadSource,
  session: UploadSession,
  store: UploadStateStore,
  onProgress?: (uploadedParts: number, totalParts: number) => void,
): Promise<CompletedPart[]> {
  const key = uploadStateKey(source);
  const previous = await store.load(key);
  const completed = new Map(
    previous?.uploadId === session.uploadId
      ? previous.completedParts.map((part) => [part.partNumber, part])
      : [],
  );

  for (const part of session.parts) {
    if (completed.has(part.partNumber)) continue;
    const start = (part.partNumber - 1) * session.partSize;
    const body = source.slice(start, Math.min(start + session.partSize, source.size));
    const response = await fetch(part.url, { method: "PUT", body });
    if (!response.ok) throw new Error(`Part ${part.partNumber} upload failed`);
    const etag = response.headers.get("etag");
    if (!etag) throw new Error(`Part ${part.partNumber} has no ETag`);
    completed.set(part.partNumber, { partNumber: part.partNumber, etag });
    await store.save(key, {
      videoId: session.videoId,
      uploadId: session.uploadId,
      fileName: source.name,
      fileSize: source.size,
      completedParts: [...completed.values()],
    });
    onProgress?.(completed.size, session.parts.length);
  }
  return [...completed.values()].sort((a, b) => a.partNumber - b.partNumber);
}

export class BrowserUploadStateStore implements UploadStateStore {
  async load(key: string) {
    const raw = globalThis.localStorage?.getItem(key);
    return raw ? (JSON.parse(raw) as UploadState) : null;
  }
  async save(key: string, state: UploadState) {
    globalThis.localStorage?.setItem(key, JSON.stringify(state));
  }
  async remove(key: string) {
    globalThis.localStorage?.removeItem(key);
  }
}
