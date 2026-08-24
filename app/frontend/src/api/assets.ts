import { request } from "./client";

export interface AssetUploadResponse {
  readonly url: string;
}

/** What the backend's magic-byte sniff accepts. Mirrors server/api/assets.py. */
export const ACCEPTED_IMAGE_TYPES = [
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
] as const;

export const MAX_ASSET_BYTES = 2 * 1024 * 1024;

/**
 * Store an image and get back a URL a mail client can fetch.
 *
 * The returned URL is public and permanent: it has to be reachable from a
 * recipient's inbox months from now, with no session behind the request.
 */
export async function uploadAsset(file: File): Promise<string> {
  const form = new FormData();
  form.append("file", file);

  const { url } = await request<AssetUploadResponse>("/assets", {
    method: "POST",
    form,
  });

  return url;
}

/** A local check so the obvious cases fail instantly instead of round-tripping. */
export function rejectionReason(file: File): string | null {
  if (file.size === 0) return "That file is empty.";

  if (file.size > MAX_ASSET_BYTES) {
    return `Images must be under ${MAX_ASSET_BYTES / 1024 / 1024} MB. This one is ${(
      file.size /
      1024 /
      1024
    ).toFixed(1)} MB.`;
  }

  // The type is advisory — the backend decides from the bytes — but catching
  // an obvious mismatch here saves a round trip.
  const accepted: readonly string[] = ACCEPTED_IMAGE_TYPES;
  if (file.type && !accepted.includes(file.type)) {
    return "Images must be PNG, JPEG, GIF, or WEBP.";
  }

  return null;
}
