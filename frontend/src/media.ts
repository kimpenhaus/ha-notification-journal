import { safeUrl } from "./markdown";
import type { NotificationRecord } from "./types";

/** The image, video and audio a notification sent, as the Companion app reads them from `data`. */
export interface Media {
  image?: string;
  video?: string;
  audio?: string;
}

const VIDEO = /^(video\/|mpeg4$|mp4$)|\.(mp4|m4v|mov|webm)$/i;
const AUDIO = /^(audio\/|mp3$|wav$|aiff$)|\.(mp3|m4a|wav|aac|ogg)$/i;

/** The Companion app's own data of a notification (`data.data`), if it sent any. */
export function appData(record: NotificationRecord): Record<string, unknown> {
  const inner = record.data?.["data"];
  return inner && typeof inner === "object" && !Array.isArray(inner) ? (inner as Record<string, unknown>) : {};
}

/**
 * The media of a notification: `image`, `video` and `audio`, and an iOS `attachment` by its content type or the
 * extension of its address. Only addresses the panel may load (see `safeUrl`).
 */
export function notificationMedia(record: NotificationRecord): Media {
  const data = appData(record);
  const media: Media = { image: safeUrl(data.image), video: safeUrl(data.video), audio: safeUrl(data.audio) };
  const attachment = data.attachment;
  if (attachment && typeof attachment === "object") {
    const { url, "content-type": type } = attachment as Record<string, unknown>;
    const address = safeUrl(url);
    if (address) {
      const kind = typeof type === "string" && type ? type : (address.split("?")[0] ?? "");
      if (VIDEO.test(kind)) media.video ??= address;
      else if (AUDIO.test(kind)) media.audio ??= address;
      else media.image ??= address;
    }
  }
  return media;
}

/** The tag a notification was sent with: a newer one with the same tag replaces it on the phone. */
export function notificationTag(record: NotificationRecord): string | undefined {
  const tag = appData(record).tag;
  return typeof tag === "string" && tag ? tag : undefined;
}

/** The name of the file an address points to. */
export function fileName(address: string): string {
  const path = address.split(/[?#]/)[0] ?? address;
  const name = path.slice(path.lastIndexOf("/") + 1);
  try {
    return decodeURIComponent(name) || address;
  } catch {
    return name || address;
  }
}
