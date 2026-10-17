import { Stack } from "expo-router";
import { CaptureProvider } from "../src/features/capture/CaptureContext";

export default function RootLayout() {
  return <CaptureProvider><Stack screenOptions={{ headerShown: false }} /></CaptureProvider>;
}
