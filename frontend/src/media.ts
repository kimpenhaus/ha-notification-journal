import { isInternal, safeUrl } from "./markdown";
import type { HassConnection, NotificationRecord } from "./types";

/** The image, video and audio a notification sent, as the Companion app reads them from `data`. */
export interface Media {
  image?: string;
  video?: string;
  audio?: string;
}

const VIDEO_TYPES = /^(video\/|public\.(movie|video|mpeg-4$)|(mpeg|mpeg2|mpeg4|mp4|avi|mov|quicktime|webm)$)/i;
const AUDIO_TYPES = /^(audio\/|public\.(audio|mp3)|(mp3|wav|aiff|m4a|mpeg4audio|aac)$)/i;
const VIDEO_FILES = /\.(mp4|m4v|mov|webm|avi|mpe?g)$/i;
const AUDIO_FILES = /\.(mp3|m4a|wav|aiff?|aac|ogg)$/i;

const SIGNED_FOR = 3600;
const SIGN_AGAIN_AFTER = (SIGNED_FOR - 600) * 1000;
const PRUNE_ABOVE = 200;
const signed = new Map<string, { until: number; path: Promise<string>; value?: string }>();

export type Signer = (path: string) => Promise<string>;

/** The Companion app's own data of a notification (`data.data`), if it sent any. */
export function appData(record: NotificationRecord): Record<string, unknown> {
  const inner = record.data?.["data"];
  return inner && typeof inner === "object" && !Array.isArray(inner) ? (inner as Record<string, unknown>) : {};
}

function kindOf(text: string, video: RegExp, audio: RegExp): keyof Media | undefined {
  if (video.test(text)) return "video";
  return audio.test(text) ? "audio" : undefined;
}

function pathOf(address: string): string {
  return address.split(/[?#]/)[0] ?? address;
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
      const kind =
        kindOf(typeof type === "string" ? type : "", VIDEO_TYPES, AUDIO_TYPES) ??
        kindOf(pathOf(address), VIDEO_FILES, AUDIO_FILES) ??
        "image";
      media[kind] ??= address;
    }
  }
  return media;
}

/** Signs a path on this Home Assistant through its connection, as its own frontend does for camera images. */
export async function signPath(connection: HassConnection, path: string): Promise<string> {
  const result = await connection.sendMessagePromise<{ path: string }>({
    type: "auth/sign_path",
    path,
    expires: SIGNED_FOR,
  });
  return result.path;
}

function ownPath(address: string): string | undefined {
  if (isInternal(address)) return address;
  try {
    const url = new URL(address);
    return url.origin === location.origin ? url.pathname + url.search : undefined;
  } catch {
    return undefined;
  }
}

/**
 * The address to load media from. A path on this Home Assistant is signed: its camera and media views need a login
 * that the browser does not send for images and videos. Signed paths are kept until shortly before they expire.
 */
export function loadable(address: string, sign: Signer | undefined): string | Promise<string> {
  const path = sign && ownPath(address);
  if (!sign || path === undefined) return address;
  const now = Date.now();
  const known = signed.get(path);
  if (known && known.until > now) return known.value ?? known.path;
  if (signed.size > PRUNE_ABOVE) for (const [key, entry] of signed) if (entry.until <= now) signed.delete(key);
  const entry: { until: number; path: Promise<string>; value?: string } = {
    until: now + SIGN_AGAIN_AFTER,
    path: sign(path)
      .catch(() => address)
      .then((value) => (entry.value = value)),
  };
  signed.set(path, entry);
  return entry.path;
}

/** What the Companion app spoke for `message: TTS` instead of showing a notification. */
export function spokenText(record: NotificationRecord): string | undefined {
  const text = record.message === "TTS" ? appData(record).tts_text : undefined;
  return typeof text === "string" && text ? text : undefined;
}

/** The tag a notification was sent with: a newer one with the same tag replaces it on the phone. */
export function notificationTag(record: NotificationRecord): string | undefined {
  const tag = appData(record).tag;
  return typeof tag === "string" && tag ? tag : undefined;
}

/** The name of the file an address points to. */
export function fileName(address: string): string {
  const path = pathOf(address);
  const name = path.slice(path.lastIndexOf("/") + 1);
  try {
    return decodeURIComponent(name) || address;
  } catch {
    return name || address;
  }
}
