/**
 * Server state, via TanStack Query.
 *
 * Query keys are namespaced by resource so a mutation can invalidate exactly
 * what it changed. Polling is deliberate and narrow — see `useCampaignStats`.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { request } from "./client";
import type {
  Campaign,
  CampaignStats,
  CcRecipient,
  Page,
  Recipient,
  RecipientUploadResult,
  SenderAddress,
  Template,
  User,
} from "./types";

export const keys = {
  me: ["me"] as const,
  campaigns: (page: number) => ["campaigns", page] as const,
  campaign: (id: string) => ["campaign", id] as const,
  stats: (id: string) => ["campaign", id, "stats"] as const,
  recipients: (id: string, page: number, status: string | null) =>
    ["campaign", id, "recipients", page, status] as const,
  ccRecipients: (id: string) => ["campaign", id, "cc"] as const,
  templates: ["templates"] as const,
  templateHtml: (id: string) => ["template", id, "html"] as const,
  senderAddresses: ["sender-addresses"] as const,
};

/* --- Session ---------------------------------------------------------- */

export function useCurrentUser(): UseQueryResult<User> {
  return useQuery({
    queryKey: keys.me,
    queryFn: () => request<User>("/auth/me"),
    // A 401 here is the answer, not a fault worth retrying.
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
}

export function useLogout() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => request<{ message: string }>("/auth/logout", { method: "POST" }),
    onSuccess: () => queryClient.clear(),
  });
}

/* --- Campaigns -------------------------------------------------------- */

export function useCampaigns(page: number) {
  return useQuery({
    queryKey: keys.campaigns(page),
    queryFn: () =>
      request<Page<Campaign>>(`/campaigns?page=${page}&page_size=20`),
  });
}

export function useCampaign(id: string) {
  return useQuery({
    queryKey: keys.campaign(id),
    queryFn: () => request<Campaign>(`/campaigns/${id}`),
  });
}

export interface CampaignInput {
  name: string;
  subject: string;
  template_body: string;
  template_id?: string | null;
  from_address?: string | null;
  cc_emails?: string[];
}

export function useCreateCampaign() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: CampaignInput) =>
      request<Campaign>("/campaigns", { method: "POST", json: input }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["campaigns"] }),
  });
}

export function useUpdateCampaign(id: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: Partial<CampaignInput>) =>
      request<Campaign>(`/campaigns/${id}`, { method: "PATCH", json: input }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.campaign(id) });
      void queryClient.invalidateQueries({ queryKey: ["campaigns"] });
    },
  });
}

export function useDeleteCampaign() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      request<void>(`/campaigns/${id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["campaigns"] }),
  });
}

/** start / pause / resume / retry — all POST, all with no body. */
export function useCampaignAction(id: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (action: "start" | "pause" | "resume" | "retry") =>
      request<Record<string, string>>(`/campaigns/${id}/${action}`, {
        method: "POST",
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.campaign(id) });
      void queryClient.invalidateQueries({ queryKey: keys.stats(id) });
      void queryClient.invalidateQueries({ queryKey: ["campaigns"] });
    },
  });
}

export function useScheduleCampaign(id: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (scheduledAt: string) =>
      request<Record<string, string>>(`/campaigns/${id}/schedule`, {
        method: "POST",
        json: { scheduled_at: scheduledAt },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.campaign(id) });
      void queryClient.invalidateQueries({ queryKey: ["campaigns"] });
    },
  });
}

/* --- Recipients ------------------------------------------------------- */

/**
 * Recipient counts, polled while there is a reason to.
 *
 * Two reasons: DNS validation is still running (the send button stays disabled
 * until `awaiting_validation` hits zero), or the campaign is sending. Otherwise
 * the numbers are settled and polling is noise.
 */
export function useCampaignStats(id: string, poll: boolean) {
  return useQuery({
    queryKey: keys.stats(id),
    queryFn: () => request<CampaignStats>(`/campaigns/${id}/stats`),
    refetchInterval: poll ? 3000 : false,
  });
}

export function useRecipients(id: string, page: number, status: string | null) {
  const query = status ? `&status=${status}` : "";

  return useQuery({
    queryKey: keys.recipients(id, page, status),
    queryFn: () =>
      request<Page<Recipient>>(
        `/campaigns/${id}/recipients?page=${page}&page_size=25${query}`,
      ),
  });
}

export function useUploadRecipients(id: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return request<RecipientUploadResult>(
        `/campaigns/${id}/recipients/upload`,
        { method: "POST", form },
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.stats(id) });
      void queryClient.invalidateQueries({ queryKey: ["campaign", id, "recipients"] });
    },
  });
}

/* --- CC --------------------------------------------------------------- */

export function useCcRecipients(id: string) {
  return useQuery({
    queryKey: keys.ccRecipients(id),
    queryFn: () => request<CcRecipient[]>(`/campaigns/${id}/cc-recipients`),
  });
}

export function useReplaceCcRecipients(id: string) {
  const queryClient = useQueryClient();

  return useMutation({
    // The endpoint replaces the whole list rather than appending.
    mutationFn: (emails: string[]) =>
      request<CcRecipient[]>(`/campaigns/${id}/cc-recipients`, {
        method: "POST",
        json: { emails },
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: keys.ccRecipients(id) }),
  });
}

/* --- Templates -------------------------------------------------------- */

export function useTemplates() {
  return useQuery({
    queryKey: keys.templates,
    queryFn: () => request<Template[]>("/templates"),
  });
}

export function useTemplateHtml(id: string | null) {
  return useQuery({
    queryKey: keys.templateHtml(id ?? ""),
    queryFn: () => request<{ html: string }>(`/templates/${id}/html`),
    enabled: id !== null,
  });
}

export function useSaveTemplate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ name, html }: { name: string; html: string }) =>
      request<Template>("/templates/html", {
        method: "POST",
        json: { name, html },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.templates }),
  });
}

export function useUpdateTemplate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      name,
      html,
    }: {
      id: string;
      name?: string;
      html: string;
    }) =>
      request<Template>(`/templates/${id}/html`, {
        method: "PUT",
        json: name === undefined ? { html } : { name, html },
      }),
    onSuccess: (_result, { id }) => {
      void queryClient.invalidateQueries({ queryKey: keys.templates });
      void queryClient.invalidateQueries({ queryKey: keys.templateHtml(id) });
    },
  });
}

export function useDeleteTemplate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      request<void>(`/templates/${id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.templates }),
  });
}

/* --- Sender addresses ------------------------------------------------- */

export function useSenderAddresses() {
  return useQuery({
    queryKey: keys.senderAddresses,
    queryFn: () => request<SenderAddress[]>("/sender-addresses"),
  });
}

export function useCreateSenderAddress() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: { label: string; email: string; is_default: boolean }) =>
      request<SenderAddress>("/sender-addresses", { method: "POST", json: input }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: keys.senderAddresses }),
  });
}

export function useUpdateSenderAddress() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      ...input
    }: {
      id: string;
      label?: string;
      is_default?: boolean;
    }) =>
      request<SenderAddress>(`/sender-addresses/${id}`, {
        method: "PATCH",
        json: input,
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: keys.senderAddresses }),
  });
}

export function useDeleteSenderAddress() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      request<void>(`/sender-addresses/${id}`, { method: "DELETE" }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: keys.senderAddresses }),
  });
}
