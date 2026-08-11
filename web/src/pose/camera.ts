/**
 * Camera acquisition.
 *
 * Requests the rear camera at 720p: enough resolution for BlazePose, low enough
 * to keep per-frame cost inside the latency budget. `getUserMedia` needs a
 * secure context — localhost is fine, a phone over the LAN needs HTTPS.
 */

export interface CameraHandle {
  stream: MediaStream;
  stop: () => void;
}

export class CameraError extends Error {
  constructor(message: string, cause?: unknown) {
    super(message, { cause });
    this.name = "CameraError";
  }
}

export async function startCamera(video: HTMLVideoElement): Promise<CameraHandle> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new CameraError(
      "Caméra indisponible. Vérifie que la page est servie en HTTPS (ou depuis localhost).",
    );
  }

  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: "environment",
        width: { ideal: 1280 },
        height: { ideal: 720 },
        frameRate: { ideal: 30 },
      },
      audio: false,
    });
  } catch (error) {
    // Distinguish "user said no" from "no camera / hardware busy": the two need
    // different instructions, and lumping them together sends people hunting for
    // a permission prompt that never appeared.
    const name = error instanceof DOMException ? error.name : "";
    if (name === "NotAllowedError") {
      throw new CameraError("Accès caméra refusé. Autorise-le puis recharge la page.", error);
    }
    if (name === "NotFoundError") {
      throw new CameraError("Aucune caméra détectée sur cet appareil.", error);
    }
    throw new CameraError("Impossible d'ouvrir la caméra.", error);
  }

  video.srcObject = stream;
  await new Promise<void>((resolve) => {
    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) return resolve();
    video.addEventListener("loadedmetadata", () => resolve(), { once: true });
  });
  await video.play();

  return {
    stream,
    stop: () => {
      for (const track of stream.getTracks()) track.stop();
      video.srcObject = null;
    },
  };
}
