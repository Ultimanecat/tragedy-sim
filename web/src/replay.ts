export interface ReplayTimelineEntry {
  number: number;
  timepoint: string;
  phase: string;
  description: string;
  steps: Array<{ timepoint: string; message: string }>;
}

/** Parse only the human-readable annotations in the stable line-oriented replay. */
export function parseReplayTimeline(text: string): ReplayTimelineEntry[] {
  const entries: ReplayTimelineEntry[] = [];
  for (const line of text.split(/\r?\n/)) {
    const action = line.match(/^ACTION\t[^\t]+\t#\s*(\d+)\s*\|\s*(.*?)\s*·\s*(.*?)\s*\|\s*(.*)$/);
    if (action) {
      entries.push({ number: Number(action[1]), timepoint: action[2], phase: action[3], description: action[4], steps: [] });
      continue;
    }
    const step = line.match(/^#\s*=>\s*\[(.*?)]\s*(.*)$/);
    if (step && entries.length) entries.at(-1)?.steps.push({ timepoint: step[1], message: step[2] });
  }
  return entries;
}
