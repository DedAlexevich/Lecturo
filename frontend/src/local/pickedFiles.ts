const files = new Map<string, File>();

export function rememberPickedFile(lectureId: string, file: File) {
  files.set(lectureId, file);
}

export function pickedFileOf(lectureId: string) {
  return files.get(lectureId) ?? null;
}

export function forgetPickedFile(lectureId: string) {
  files.delete(lectureId);
}
