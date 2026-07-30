/**
 * Read an image File and return a downscaled JPEG data URI.
 *
 * KYC documents are stored as base64 on the server, so we shrink before upload: cap the longest side
 * and re-encode as JPEG. A phone photo (several MB) becomes a couple hundred KB — small enough to
 * store and send, still legible for an operator to read the ID.
 */
export async function fileToDownscaledDataUrl(file: File, maxSide = 1280, quality = 0.7): Promise<string> {
  if (!file.type.startsWith("image/")) throw new Error("Please choose an image file");

  const dataUrl = await new Promise<string>((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(fr.result as string);
    fr.onerror = () => reject(new Error("Could not read the file"));
    fr.readAsDataURL(file);
  });

  const img = await new Promise<HTMLImageElement>((resolve, reject) => {
    const i = new Image();
    i.onload = () => resolve(i);
    i.onerror = () => reject(new Error("Could not decode the image"));
    i.src = dataUrl;
  });

  const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
  const w = Math.round(img.width * scale);
  const h = Math.round(img.height * scale);
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) return dataUrl; // no canvas → fall back to the original
  ctx.drawImage(img, 0, 0, w, h);
  return canvas.toDataURL("image/jpeg", quality);
}
