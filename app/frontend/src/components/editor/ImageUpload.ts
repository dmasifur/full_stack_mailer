/**
 * The R2 image pipeline, as a TipTap extension.
 *
 * Four ways an image enters a document, all funnelled through one path:
 *
 *   1. Pasting image files — a screenshot straight from the clipboard.
 *   2. Pasting HTML with `data:` images — how Word and Google Docs carry them.
 *   3. Dragging files onto the editor.
 *   4. The toolbar button.
 *
 * Every one of them uploads first and inserts a public URL. A `data:` URI left
 * in the body would be inlined into the message: Gmail clips a message over
 * 102 KB, and a base64 image blows past that on its own.
 *
 * Uploads are counted rather than given placeholder nodes: the toolbar shows
 * how many are in flight, and each image appears at the cursor as its URL
 * arrives. One failure is reported and skipped — it never costs the rest.
 */

import { Extension } from "@tiptap/core";
import type { Editor } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import type { EditorView } from "@tiptap/pm/view";

import { rejectionReason, uploadAsset } from "@/api/assets";
import { cleanPastedHtml, dataUriToFile, findDataUriImages } from "./pasteCleanup";

/** A pasted document can carry a dozen images; don't open a dozen sockets. */
const MAX_CONCURRENT_UPLOADS = 3;

export interface ImageUploadOptions {
  /** Surfaced to the user. The editor cannot decide what to do about a failure. */
  onError: (message: string) => void;
  /** Fired as uploads start and finish, for a progress indicator. */
  onPendingChange?: (pending: number) => void;
}

interface UploadTracker {
  pending: number;
  readonly options: ImageUploadOptions;
}

function track(tracker: UploadTracker, delta: number): void {
  tracker.pending += delta;
  tracker.options.onPendingChange?.(tracker.pending);
}

/**
 * Upload one file and insert it at the current selection.
 *
 * Errors are reported, never thrown: one bad image out of ten should not lose
 * the other nine.
 */
async function uploadAndInsert(
  editor: Editor,
  file: File,
  tracker: UploadTracker,
): Promise<void> {
  const rejection = rejectionReason(file);
  if (rejection !== null) {
    tracker.options.onError(rejection);
    return;
  }

  track(tracker, 1);
  try {
    const src = await uploadAsset(file);
    editor.chain().focus().setImage({ src, alt: file.name }).run();
  } catch (error) {
    tracker.options.onError(
      error instanceof Error
        ? `${file.name} could not be uploaded. ${error.message}`
        : `${file.name} could not be uploaded.`,
    );
  } finally {
    track(tracker, -1);
  }
}

/** Run tasks a few at a time, so a big paste does not flood the network. */
async function inBatches<T>(
  items: readonly T[],
  run: (item: T) => Promise<void>,
): Promise<void> {
  for (let i = 0; i < items.length; i += MAX_CONCURRENT_UPLOADS) {
    const slice = items.slice(i, i + MAX_CONCURRENT_UPLOADS);
    await Promise.all(slice.map(run));
  }
}

function imageFilesIn(list: DataTransfer | null): File[] {
  if (!list) return [];
  return Array.from(list.files).filter((file) => file.type.startsWith("image/"));
}

/**
 * Replace every `data:` image in pasted HTML with an uploaded URL.
 *
 * Returns the rewritten HTML. An image that fails to upload is dropped from
 * the markup rather than left as a data URI — leaving it would quietly bloat
 * the message past Gmail's clipping threshold.
 */
export async function rewriteDataUriImages(
  html: string,
  onError: (message: string) => void,
): Promise<string> {
  const uris = findDataUriImages(html);
  if (uris.length === 0) return html;

  const replacements = new Map<string, string | null>();

  await inBatches(uris, async (uri) => {
    if (replacements.has(uri)) return;
    try {
      const file = await dataUriToFile(uri, "pasted-image");
      const rejection = rejectionReason(file);
      if (rejection !== null) {
        onError(rejection);
        replacements.set(uri, null);
        return;
      }
      replacements.set(uri, await uploadAsset(file));
    } catch {
      onError("A pasted image could not be uploaded and was left out.");
      replacements.set(uri, null);
    }
  });

  let rewritten = html;
  for (const [uri, url] of replacements) {
    rewritten =
      url === null
        ? rewritten.replace(
            new RegExp(`<img\\b[^>]*src="${escapeRegExp(uri)}"[^>]*>`, "gi"),
            "",
          )
        : rewritten.split(uri).join(url);
  }

  return rewritten;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export const ImageUpload = Extension.create<ImageUploadOptions>({
  name: "imageUpload",

  addOptions() {
    return {
      onError: () => {},
    };
  },

  addProseMirrorPlugins() {
    const { editor, options } = this;
    const tracker: UploadTracker = { pending: 0, options };

    return [
      new Plugin({
        key: new PluginKey("imageUpload"),
        props: {
          handlePaste(_view: EditorView, event: ClipboardEvent) {
            const files = imageFilesIn(event.clipboardData);
            if (files.length > 0) {
              // Handled here, so the default paste does not also insert a
              // data: URI alongside the uploaded copy.
              event.preventDefault();
              void inBatches(files, (file) =>
                uploadAndInsert(editor, file, tracker),
              );
              return true;
            }

            // Word and Google Docs carry their images inside the HTML flavour
            // as data: URIs. Uploading them needs a round trip, which
            // transformPastedHTML cannot do — it is synchronous — so the paste
            // is taken over here and inserted once the URLs are back.
            const html = event.clipboardData?.getData("text/html");
            if (!html?.includes("data:image/")) return false;

            event.preventDefault();
            track(tracker, 1);
            void rewriteDataUriImages(cleanPastedHtml(html), options.onError)
              .then((rewritten) => {
                // insertContent, not setContent: the paste goes in at the
                // cursor. setContent would replace the whole document and
                // throw away everything already written.
                editor.commands.insertContent(rewritten);
              })
              .finally(() => track(tracker, -1));
            return true;
          },

          handleDrop(_view: EditorView, event: DragEvent) {
            const files = imageFilesIn(event.dataTransfer);
            if (files.length === 0) return false;

            event.preventDefault();
            void inBatches(files, (file) =>
              uploadAndInsert(editor, file, tracker),
            );
            return true;
          },
        },
      }),
    ];
  },
});

/** The toolbar's entry point: pick a file, upload it, insert it. */
export function pickAndUploadImage(
  editor: Editor,
  options: ImageUploadOptions,
): void {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "image/png,image/jpeg,image/gif,image/webp";

  input.addEventListener("change", () => {
    const file = input.files?.[0];
    if (file) {
      void uploadAndInsert(editor, file, { pending: 0, options });
    }
  });

  input.click();
}
