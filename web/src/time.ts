/** A stored time, which is UTC: one saved before the offset was written down has none, and is UTC
 * too, so it is not read as the viewer's local time. Shown in the viewer's local time (labels.when). */
export const instant = (iso: string) => new Date(/T\d\d:\d\d(:\d\d(\.\d+)?)?$/.test(iso) ? `${iso}Z` : iso);
