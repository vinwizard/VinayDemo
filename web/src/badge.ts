/** A report tab's badge: what it counts, in words ("3 claims"), never a bare 0 that reads as a
 * grade ("Win it back 0" did). `none` is what a tab with nothing to count shows: a tick where empty
 * is good news, else no badge at all. */
export const tabBadge = (n: number | undefined, one: string, none?: string) =>
  n == null ? undefined : n ? `${n} ${n === 1 ? one : `${one}s`}` : none;
