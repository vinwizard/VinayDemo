/** What the grouping reads of an investigation (api.Investigation has these fields and more). */
export interface Grouped { id: string; attribute_id: string; question: string; created_at: string }

/**
 * One entry per claim and question: the newest investigation leads, the older ones sit behind it.
 * Re-asking why about the same claim and question gives a fresh result (what AI reads changes from
 * day to day); showing every run side by side read as two contradicting cards for one claim.
 */
export function latestPerClaim<T extends Grouped>(invs: T[]): { latest: T; earlier: T[] }[] {
  const groups = new Map<string, T[]>();
  for (const inv of [...invs].sort((a, b) => b.created_at.localeCompare(a.created_at))) {
    const key = `${inv.attribute_id}\n${inv.question.trim().toLowerCase()}`;
    groups.set(key, [...(groups.get(key) ?? []), inv]);
  }
  return [...groups.values()].map(([latest, ...earlier]) => ({ latest, earlier }));
}
