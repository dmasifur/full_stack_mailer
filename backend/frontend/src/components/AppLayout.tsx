import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { useLogout } from "@/api/hooks";
import type { User } from "@/api/types";
import { Button } from "./ui/primitives";

const NAV = [
  { to: "/", label: "Campaigns", end: true },
  { to: "/templates", label: "Templates", end: false },
  { to: "/settings", label: "Settings", end: false },
];

export function AppLayout({
  user,
  children,
}: {
  user: User;
  children: ReactNode;
}) {
  const logout = useLogout();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-bg text-text">
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-4">
          {/* Guide §7: Geist Bold, all lowercase. The mark itself is still a
              placeholder in brand guide v1.0 — this slot is ready for it. */}
          <button
            type="button"
            onClick={() => void navigate("/")}
            className="font-heading text-h4 font-black tracking-tight"
          >
            asifur<span className="text-accent">.dev</span>
          </button>

          <nav className="flex gap-1">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  [
                    "rounded px-3 py-1.5 text-small transition-colors",
                    isActive
                      ? "bg-surface text-text"
                      : "text-muted hover:text-text",
                  ].join(" ")
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <span className="font-mono text-inline text-muted">{user.email}</span>
            <Button
              variant="ghost"
              onClick={() => {
                logout.mutate(undefined, {
                  // A full navigation, not a route change: the server clears
                  // the cookie and the app has to start from nothing.
                  onSettled: () => window.location.assign("/app"),
                });
              }}
            >
              Sign out
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-10">{children}</main>
    </div>
  );
}
