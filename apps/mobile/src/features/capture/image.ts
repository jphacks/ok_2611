const maxBytes = 2 * 1024 * 1024;
const maxPixels = 20_000_000;
const maxEdge = 1600;

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("Could not read this image. Choose another photo."));
    image.src = url;
  });
}

function toJpeg(canvas: HTMLCanvasElement, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => blob ? resolve(blob) : reject(new Error("Could not prepare this photo.")),
      "image/jpeg",
      quality,
    );
  });
}

export async function prepareMenuImage(file: File): Promise<File> {
  if (file.type !== "image/jpeg" && file.type !== "image/png") {
    throw new Error("Choose a JPEG or PNG image.");
  }

  const objectUrl = URL.createObjectURL(file);
  let image: HTMLImageElement;
  try {
    image = await loadImage(objectUrl);
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
  const width = image.naturalWidth;
  const height = image.naturalHeight;
  if (!width || !height) throw new Error("Could not read this image.");
  if (width * height > maxPixels) throw new Error("This image exceeds 20 million pixels. Choose a smaller photo.");

  const scale = Math.min(1, maxEdge / Math.max(width, height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Could not prepare this photo.");
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);

  for (const quality of [0.85, 0.72, 0.58, 0.42]) {
    const blob = await toJpeg(canvas, quality);
    if (blob.size <= maxBytes) {
      return new File([blob], "menu-photo.jpg", { type: "image/jpeg" });
    }
  }
  throw new Error("This photo is larger than 2 MiB after compression. Choose another photo.");
}
