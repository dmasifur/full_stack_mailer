/**
 * The shared vocabulary every screen is built from.
 *
 * Brand guide v1.0: depth comes from surface elevation and 1px borders, never
 * gradients or drop shadows. Geist for headings, DM Sans for copy, JetBrains
 * Mono for anything technical — addresses, ids, code, failure reasons.
 */

import type { ButtonHTMLAttributes, ReactNode } from "react";

import type { CampaignStatus } from "@/lib/campaignState";

function join(...classes: (string | false | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

/* --- Buttons ---------------------------------------------------------- */

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-text hover:bg-accent-2 border border-transparent",
  secondary: "bg-surface text-text hover:border-accent border border-border",
  ghost: "bg-transparent text-muted hover:text-text border border-transparent",
  // Outline, not filled: a destructive action should be legible without
  // shouting, and a solid red block would be a third accent on the screen.
  danger: "bg-transparent text-danger hover:bg-danger/10 border border-danger/40",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant | undefined;
}

export function Button({
  variant = "secondary",
  className,
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      className={join(
        "inline-flex items-center gap-2 rounded px-3 py-1.5 text-small font-medium",
        "transition-colors disabled:cursor-not-allowed disabled:opacity-40",
        VARIANTS[variant],
        className,
      )}
    />
  );
}

/* --- Surfaces --------------------------------------------------------- */

export function Card({
  children,
  className,
}: {
  children: ReactNode;
  className?: string | undefined;
}) {
  return (
    <div
      className={join(
        "rounded-lg border border-border bg-surface/40 p-5",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function PageHeading({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string | undefined;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-8 flex items-start justify-between gap-4">
      <div>
        <h1 className="font-heading text-h3 font-bold">{title}</h1>
        {subtitle ? <p className="mt-1 text-small text-muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 gap-2">{actions}</div> : null}
    </header>
  );
}

/* --- Status ----------------------------------------------------------- */

/**
 * Status colour lives off the accent channel.
 *
 * The guide allows at most two accent colours on screen at once. Statuses are
 * rendered as a dot plus text on the surface colour, never as filled blocks,
 * so a page full of badges still reads as one blue accent and one neutral.
 */
const STATUS_DOT: Record<CampaignStatus, string> = {
  draft: "bg-muted",
  scheduled: "bg-accent",
  running: "bg-accent animate-pulse",
  paused: "bg-warn",
  completed: "bg-success",
  failed: "bg-danger",
};

const RECIPIENT_DOT: Record<string, string> = {
  pending_validation: "bg-muted",
  pending: "bg-muted",
  sending: "bg-accent animate-pulse",
  sent: "bg-success",
  failed: "bg-danger",
  invalid: "bg-warn",
};

export function StatusBadge({ status }: { status: string }) {
  const dot = STATUS_DOT[status as CampaignStatus] ?? RECIPIENT_DOT[status] ?? "bg-muted";

  return (
    <span className="inline-flex items-center gap-2 rounded border border-border bg-surface/60 px-2 py-0.5 text-caption">
      <span className={join("size-1.5 rounded-full", dot)} aria-hidden />
      <span className="font-mono text-label uppercase tracking-wide">
        {status.replace(/_/g, " ")}
      </span>
    </span>
  );
}

/* --- Feedback --------------------------------------------------------- */

type NoticeTone = "info" | "warn" | "danger" | "success";

const NOTICE_TONES: Record<NoticeTone, string> = {
  info: "border-accent/40 text-text",
  warn: "border-warn/40 text-text",
  danger: "border-danger/40 text-text",
  success: "border-success/40 text-text",
};

export function Notice({
  tone = "info",
  title,
  children,
}: {
  tone?: NoticeTone | undefined;
  title?: string | undefined;
  children: ReactNode;
}) {
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={join(
        "rounded border bg-surface/40 px-4 py-3 text-small",
        NOTICE_TONES[tone],
      )}
    >
      {title ? <p className="mb-1 font-medium">{title}</p> : null}
      <div className="text-muted">{children}</div>
    </div>
  );
}

/** Empty states say what to do next, in one line. */
export function EmptyState({
  message,
  action,
}: {
  message: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-dashed border-border px-6 py-12 text-center">
      <p className="text-small text-muted">{message}</p>
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-small text-muted">
      <span
        className="size-3 animate-spin rounded-full border-2 border-border border-t-accent"
        aria-hidden
      />
      {label}
    </span>
  );
}

/* --- Forms ------------------------------------------------------------ */

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string | undefined;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-small font-medium">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-caption text-muted">{hint}</span> : null}
    </label>
  );
}

export const inputClass =
  "w-full rounded border border-border bg-bg px-3 py-2 text-small " +
  "placeholder:text-muted focus:border-accent focus:outline-none";

/** For addresses, ids, keys, and failure reasons — guide §5. */
export function Mono({ children }: { children: ReactNode }) {
  return <span className="font-mono text-inline">{children}</span>;
}
