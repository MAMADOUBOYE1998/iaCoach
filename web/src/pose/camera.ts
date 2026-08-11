/**
 * Camera acquisition.
 *
 * 720p: enough resolution for BlazePose, low enough to keep per-frame cost
 * inside the latency budget. `getUserMedia` needs a secure context — localhost
 * is fine, a phone over the LAN needs HTTPS.
 *
 * Which camera is a real choice, not a detail. The front camera lets the athlete
 * see the preview and frame themselves before starting; the rear one is usually
 * the better sensor. Neither wins in general, so both are reachable and the
 * choice is remembered.
 */

/** `user` = front (selfie), `environment` = rear. */
export type Facing = "user" | "environment";

export interface CameraHandle {
  stream: MediaStream;
  /** What we actually got, which is not always what we asked for. */
  facing: Facing;
  /**
   * Whether the preview should be flipped horizontally.
   *
   * True only when the track *reports* a front camera — a phone selfie view,
   * where an unmirrored preview feels wrong to everyone who has ever used a
   * mirror in a gym. A laptop webcam reports no `facingMode` at all, and is
   * deliberately left alone: it already looks right, and guessing would break
   * a setup that works. Mirroring is purely visual — the landmarks, and every
   * metric built on them, are anatomically labelled either way.
   */
  mirrored: boolean;
  stop: () => void;
}

export class CameraError extends Error {
  constructor(message: string, cause?: unknown) {
    super(message, { cause });
    this.name = "CameraError";
  }
}

export function otherFacing(facing: Facing): Facing {
  return facing === "user" ? "environment" : "user";
}

/**
 * Does this device have more than one camera?
 *
 * Used to decide whether to offer the switch at all. Only meaningful once
 * permission has been granted — before that, browsers hide the device list.
 * A failure answers "no": offering a switch that cannot work is worse than not
 * offering one.
 */
export async function hasMultipleCameras(): Promise<boolean> {
  if (!navigator.mediaDevices?.enumerateDevices) return false;
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((d) => d.kind === "videoinput").length > 1;
  } catch {
    return false;
  }
}

function constraints(facing: Facing, exact: boolean): MediaStreamConstraints {
  return {
    video: {
      facingMode: exact ? { exact: facing } : facing,
      width: { ideal: 1280 },
      height: { ideal: 720 },
      frameRate: { ideal: 30 },
    },
    audio: false,
  };
}

export async function startCamera(
  video: HTMLVideoElement,
  facing: Facing = "user",
): Promise<CameraHandle> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new CameraError(
      "Caméra indisponible. Vérifie que la page est servie en HTTPS (ou depuis localhost).",
    );
  }

  let stream: MediaStream;
  try {
    // `exact` first, because a phone with two cameras ignores a soft preference
    // often enough that the switch button would do nothing. Laptops with a
    // single camera reject it, hence the fallback — a machine with one camera
    // should open it, not report a failure.
    try {
      stream = await navigator.mediaDevices.getUserMedia(constraints(facing, true));
    } catch (error) {
      const name = error instanceof DOMException ? error.name : "";
      if (name !== "OverconstrainedError" && name !== "NotFoundError") throw error;
      stream = await navigator.mediaDevices.getUserMedia(constraints(facing, false));
    }
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

  const reported = settingsFacing(stream);
  return {
    stream,
    facing: reported ?? facing,
    mirrored: reported === "user",
    stop: () => {
      for (const track of stream.getTracks()) track.stop();
      video.srcObject = null;
    },
  };
}

/**
 * What the track reports, which can differ from what was requested — a laptop
 * webcam usually reports no `facingMode` at all. Returning `null` there keeps
 * the caller from mirroring a preview that is not a selfie view.
 */
function settingsFacing(stream: MediaStream): Facing | null {
  const reported = stream.getVideoTracks()[0]?.getSettings().facingMode;
  return reported === "user" || reported === "environment" ? reported : null;
}
