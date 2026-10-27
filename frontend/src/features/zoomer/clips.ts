const modules = import.meta.glob<string>("/src/assets/zoomer/*.{mp4,webm}", {
  eager: true,
  query: "?url",
  import: "default",
});

export const zoomerClips: string[] = Object.keys(modules)
  .sort()
  .map((path) => modules[path]);
