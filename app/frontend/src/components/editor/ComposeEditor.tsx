/**
 * The rich-text half of the editor.
 *
 * Everything here serves one goal: the HTML that leaves this component has to
 * survive Outlook. That rules out the editor's own class names, pasted Word
 * cruft, and `data:` images — see pasteCleanup.ts and ImageUpload.ts.
 */

import { EditorContent, useEditor } from "@tiptap/react";
import type { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import Image from "@tiptap/extension-image";
import Link from "@tiptap/extension-link";
import TextAlign from "@tiptap/extension-text-align";
import Underline from "@tiptap/extension-underline";
import { useState } from "react";

import { Button, Mono } from "@/components/ui/primitives";
import { ImageUpload, pickAndUploadImage } from "./ImageUpload";
import { MERGE_TAGS, MergeTag, tokensToChips } from "./MergeTag";
import { cleanPastedHtml } from "./pasteCleanup";

interface ComposeEditorProps {
  readonly initialContent: string;
  readonly onChange: (html: string) => void;
  readonly onError: (message: string) => void;
}

export function ComposeEditor({
  initialContent,
  onChange,
  onError,
}: ComposeEditorProps) {
  const [pendingUploads, setPendingUploads] = useState(0);

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        // Neither survives an email client worth designing for.
        codeBlock: false,
        horizontalRule: {},
      }),
      Underline,
      Link.configure({ openOnClick: false, autolink: true }),
      Image.configure({ inline: false, allowBase64: false }),
      TextAlign.configure({ types: ["heading", "paragraph"] }),
      MergeTag,
      ImageUpload.configure({
        onError,
        onPendingChange: setPendingUploads,
      }),
    ],
    // Tokens typed by hand, or written in source mode, become chips on the
    // way in — so the editor shows one consistent thing however they arrived.
    content: tokensToChips(initialContent),
    editorProps: {
      attributes: {
        // The canvas is light on purpose — it shows what a recipient sees.
        class:
          "prose-email min-h-[24rem] bg-canvas text-canvas-text px-8 py-6 " +
          "focus:outline-none",
      },
      transformPastedHTML: cleanPastedHtml,
    },
    onUpdate: ({ editor: instance }) => onChange(instance.getHTML()),
  });

  if (!editor) return null;

  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <Toolbar
        editor={editor}
        pendingUploads={pendingUploads}
        onError={onError}
      />
      {/* The border marks where the app stops and the email begins. */}
      <div className="border-t border-border bg-canvas">
        <EditorContent editor={editor} />
      </div>
    </div>
  );
}

function Toolbar({
  editor,
  pendingUploads,
  onError,
}: {
  editor: Editor;
  pendingUploads: number;
  onError: (message: string) => void;
}) {
  const mark = (name: string, attrs?: Record<string, unknown>) =>
    editor.isActive(name, attrs) ? "primary" : "ghost";

  return (
    <div className="flex flex-wrap items-center gap-1 bg-surface/40 p-2">
      <Button
        variant={mark("bold")}
        onClick={() => editor.chain().focus().toggleBold().run()}
        title="Bold"
      >
        <strong>B</strong>
      </Button>
      <Button
        variant={mark("italic")}
        onClick={() => editor.chain().focus().toggleItalic().run()}
        title="Italic"
      >
        <em>I</em>
      </Button>
      <Button
        variant={mark("underline")}
        onClick={() => editor.chain().focus().toggleUnderline().run()}
        title="Underline"
      >
        <span className="underline">U</span>
      </Button>

      <Divider />

      {([1, 2, 3] as const).map((level) => (
        <Button
          key={level}
          variant={mark("heading", { level })}
          onClick={() => editor.chain().focus().toggleHeading({ level }).run()}
          title={`Heading ${level}`}
        >
          H{level}
        </Button>
      ))}

      <Divider />

      <Button
        variant={mark("bulletList")}
        onClick={() => editor.chain().focus().toggleBulletList().run()}
        title="Bullet list"
      >
        List
      </Button>
      <Button
        variant={mark("orderedList")}
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
        title="Numbered list"
      >
        1.
      </Button>
      <Button
        variant={mark("blockquote")}
        onClick={() => editor.chain().focus().toggleBlockquote().run()}
        title="Quote"
      >
        Quote
      </Button>

      <Divider />

      {(["left", "center", "right"] as const).map((alignment) => (
        <Button
          key={alignment}
          variant={editor.isActive({ textAlign: alignment }) ? "primary" : "ghost"}
          onClick={() => editor.chain().focus().setTextAlign(alignment).run()}
          title={`Align ${alignment}`}
        >
          {alignment[0]?.toUpperCase()}
        </Button>
      ))}

      <Divider />

      <Button variant="ghost" onClick={() => promptForLink(editor)} title="Link">
        Link
      </Button>
      <Button
        variant="ghost"
        onClick={() => pickAndUploadImage(editor, { onError })}
        title="Insert an image"
      >
        Image
      </Button>

      <Divider />

      <MergeTagMenu editor={editor} />

      {pendingUploads > 0 ? (
        <span className="ml-auto text-caption text-muted">
          Uploading {pendingUploads} image{pendingUploads === 1 ? "" : "s"}…
        </span>
      ) : null}
    </div>
  );
}

function Divider() {
  return <span className="mx-1 h-5 w-px bg-border" aria-hidden />;
}

function MergeTagMenu({ editor }: { editor: Editor }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <Button variant="ghost" onClick={() => setOpen((on) => !on)}>
        <Mono>{"{{ }}"}</Mono> Merge tag
      </Button>

      {open ? (
        <div className="absolute z-10 mt-1 w-72 rounded border border-border bg-surface p-1">
          {MERGE_TAGS.map((tag) => (
            <button
              key={tag.token}
              type="button"
              className="block w-full rounded px-3 py-2 text-left hover:bg-bg"
              onClick={() => {
                // A fallback is prompted for, not assumed: most CSVs have rows
                // with no first name, and "Hi ," is worse than "Hi there,".
                const fallback =
                  tag.token === "email"
                    ? ""
                    : (window.prompt(
                        `Fallback if ${tag.label.toLowerCase()} is blank (optional)`,
                        "there",
                      ) ?? "");
                editor.chain().focus().insertMergeTag(tag.token, fallback).run();
                setOpen(false);
              }}
            >
              <span className="block text-small font-medium">{tag.label}</span>
              <span className="block text-caption text-muted">{tag.description}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function promptForLink(editor: Editor): void {
  const existing = String(editor.getAttributes("link").href ?? "");
  const href = window.prompt("Link URL", existing);

  if (href === null) return;

  if (href === "") {
    editor.chain().focus().unsetLink().run();
    return;
  }

  editor.chain().focus().extendMarkRange("link").setLink({ href }).run();
}
