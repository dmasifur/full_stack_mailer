/** Parsing the CC field: people paste commas, semicolons, or one per line. */
export function splitEmails(raw: string): string[] {
  return raw
    .split(/[,\n;]/)
    .map((value) => value.trim())
    .filter((value) => value !== "");
}
