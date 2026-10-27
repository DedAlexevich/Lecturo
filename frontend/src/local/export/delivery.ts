export type LocalDelivery = "download" | "dialog";

export type ShareMode = "file" | "text" | "none";

type ShareSupport = {
  share?: unknown;
  canShare?: (data: { files: File[] }) => boolean;
};

export function chooseLocalDelivery(inMiniApp: boolean): LocalDelivery {
  return inMiniApp ? "dialog" : "download";
}

export function chooseShareMode(support: ShareSupport, file: File | null): ShareMode {
  if (typeof support.share !== "function") return "none";
  if (!file || typeof support.canShare !== "function") return "text";
  try {
    return support.canShare({ files: [file] }) ? "file" : "text";
  } catch {
    return "text";
  }
}
