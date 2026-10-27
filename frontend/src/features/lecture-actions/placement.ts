export type MenuPlacement = { left: number; width?: number };

export function placeMenu(
  trigger: { left: number; right: number },
  menuWidth: number,
  viewportWidth: number,
  gutter = 8,
): MenuPlacement {
  const alignedRight = trigger.right - menuWidth;
  if (alignedRight >= gutter) return { left: alignedRight - trigger.left };
  if (trigger.left + menuWidth <= viewportWidth - gutter) return { left: 0 };
  return { left: gutter - trigger.left, width: viewportWidth - gutter * 2 };
}
