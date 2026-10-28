import { plural } from "../../lib/plural";

export function ticketsCount(count: number) {
  return `${count} ${plural(count, "билет", "билета", "билетов")}`;
}

export function definitionsCount(count: number) {
  return `${count} ${plural(count, "определение", "определения", "определений")}`;
}
