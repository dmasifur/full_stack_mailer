import { LOGIN_URL } from "@/api/client";
import { Button, Notice } from "@/components/ui/primitives";

export function LoginPage({ error }: { error?: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="w-full max-w-sm">
        <p className="font-heading text-h2 font-black tracking-tight">
          asifur<span className="text-accent">.dev</span>
        </p>
        <p className="mt-2 text-small text-muted">Mailer</p>

        <p className="mt-8 text-small text-muted">
          Campaigns send from your own Microsoft mailbox. Connect it to begin.
        </p>

        <Button
          variant="primary"
          className="mt-6 w-full justify-center py-2.5"
          onClick={() => {
            // A full navigation: this is the start of an OAuth redirect chain,
            // not something fetch can follow.
            window.location.assign(LOGIN_URL);
          }}
        >
          Connect Microsoft account
        </Button>

        {error ? (
          <div className="mt-6">
            <Notice tone="danger">{error}</Notice>
          </div>
        ) : null}
      </div>
    </div>
  );
}
