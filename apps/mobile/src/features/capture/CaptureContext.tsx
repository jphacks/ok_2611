import { createContext, useContext, useEffect, useState, type PropsWithChildren } from "react";

type CapturedImage = { file: File; url: string };
type CaptureState = {
  image: CapturedImage | null;
  setImage: (file: File) => void;
  clearImage: () => void;
};

const CaptureContext = createContext<CaptureState | null>(null);

export function CaptureProvider({ children }: PropsWithChildren) {
  const [image, setCapturedImage] = useState<CapturedImage | null>(null);

  useEffect(() => {
    return () => {
      if (image) URL.revokeObjectURL(image.url);
    };
  }, [image]);

  return (
    <CaptureContext.Provider value={{
      image,
      setImage: (file) => setCapturedImage({ file, url: URL.createObjectURL(file) }),
      clearImage: () => setCapturedImage(null),
    }}>
      {children}
    </CaptureContext.Provider>
  );
}

export function useCapture() {
  const state = useContext(CaptureContext);
  if (!state) throw new Error("CaptureProvider is missing");
  return state;
}
