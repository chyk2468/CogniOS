import type { Attachment } from "../types";

export function SessionIntro(_props: {
  sessionId: string;
  onOpenSessionSettings: () => void;
  onPrefill: (text: string, attachments?: Attachment[]) => void;
}) {
  return null;
}
