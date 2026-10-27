import { lectureSeconds } from "./format";
import type { Waiting } from "./queries";

export type Plan = {
  source: Waiting | undefined;
  order: string[];
  selected: string[];
};

export const emptyPlan: Plan = { source: undefined, order: [], selected: [] };

export function mergePlan(plan: Plan, waiting: Waiting): Plan {
  const seconds = new Map(waiting.lectures.map((lecture) => [lecture.id, lectureSeconds(lecture.duration_sec)]));
  const kept = plan.order.filter((id) => seconds.has(id));
  const added = waiting.lectures.map((lecture) => lecture.id).filter((id) => !kept.includes(id));
  const selected = plan.selected.filter((id) => seconds.has(id));
  let used = selected.reduce((sum, id) => sum + (seconds.get(id) ?? 0), 0);
  for (const id of added) {
    const needed = seconds.get(id) ?? 0;
    if (used + needed <= waiting.available_sec) {
      selected.push(id);
      used += needed;
    }
  }
  return { source: waiting, order: [...kept, ...added], selected };
}

export function moveTo(order: string[], id: string, index: number) {
  const rest = order.filter((item) => item !== id);
  const target = Math.max(0, Math.min(rest.length, index));
  return [...rest.slice(0, target), id, ...rest.slice(target)];
}

export function plannedIds(plan: Plan) {
  return plan.order.filter((id) => plan.selected.includes(id));
}
