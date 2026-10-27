declare module "markdown-it-texmath" {
  import type { PluginWithOptions } from "markdown-it";

  const texmath: PluginWithOptions<Record<string, unknown>>;
  export default texmath;
}
