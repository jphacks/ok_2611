import { createElement, useCallback, useRef, useState, type ChangeEvent } from "react";
import { CameraView, useCameraPermissions } from "expo-camera";
import { router, useFocusEffect, useLocalSearchParams } from "expo-router";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { PrimaryButton } from "../../src/components/PrimaryButton";
import { useCapture } from "../../src/features/capture/CaptureContext";
import { prepareMenuImage } from "../../src/features/capture/image";
import { colors } from "../../src/theme";

export default function CaptureScreen() {
  const { google_place_id: placeId, restaurant_name: restaurantName } = useLocalSearchParams<{
    google_place_id?: string; restaurant_name?: string;
  }>();
  const { setImage } = useCapture();
  const [permission, requestPermission] = useCameraPermissions();
  const cameraRef = useRef<CameraView>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [focused, setFocused] = useState(true);
  const [cameraReady, setCameraReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useFocusEffect(useCallback(() => {
    setFocused(true);
    setCameraReady(false);
    return () => {
      setFocused(false);
      setCameraReady(false);
    };
  }, []));

  async function acceptFile(file: File) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const prepared = await prepareMenuImage(file);
      setImage(prepared);
      router.push({ pathname: "/capture/preview", params: placeId ? { google_place_id: placeId, restaurant_name: restaurantName } : {} });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not prepare this photo.");
    } finally {
      setBusy(false);
    }
  }

  async function takePhoto() {
    if (!cameraReady || !cameraRef.current || busy) return;
    setBusy(true);
    setError("");
    try {
      const photo = await cameraRef.current.takePictureAsync({ imageType: "jpg", quality: 0.85, exif: false });
      const blob = await fetch(photo.uri).then((response) => response.blob());
      const prepared = await prepareMenuImage(new File([blob], "camera.jpg", { type: "image/jpeg" }));
      setImage(prepared);
      router.push({ pathname: "/capture/preview", params: placeId ? { google_place_id: placeId, restaurant_name: restaurantName } : {} });
    } catch {
      setError("Could not take the photo. Try again or choose a photo.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <View style={styles.darkArea}>
        {restaurantName ? <Text style={styles.restaurant}>{restaurantName}</Text> : null}
        <View style={styles.cameraFrame}>
          {focused && permission?.granted ? (
            <CameraView
              ref={cameraRef}
              style={styles.camera}
              facing="back"
              onCameraReady={() => setCameraReady(true)}
              onMountError={() => { setCameraReady(false); setError("Camera is unavailable. Choose a photo below."); }}
            />
          ) : (
            <View style={styles.cameraFallback}>
              <Text style={styles.cameraMessage}>
                {permission ? "Allow camera access to take a photo." : "Checking camera access…"}
              </Text>
              {permission && !permission.granted ? (
                <PrimaryButton label="Allow camera" onPress={() => { void requestPermission(); }} />
              ) : null}
            </View>
          )}
        </View>
        {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={cameraReady ? "Take photo" : "Choose a menu photo"}
          accessibilityState={{ disabled: busy }}
          disabled={busy}
          onPress={() => { if (cameraReady) void takePhoto(); else fileRef.current?.click(); }}
          style={[styles.shutter, busy && styles.shutterDisabled]}
        ><View style={styles.shutterInner} /></Pressable>
      </View>
      <View style={styles.navigation}>
        <Pressable onPress={() => router.replace("/map")} accessibilityRole="button" style={styles.tab}>
          <Text style={styles.navIcon}>⌖</Text><Text style={styles.navText}>Map</Text>
        </Pressable>
        <View style={styles.tab}><Text style={styles.navIconSelected}>⌗</Text><Text style={styles.navSelected}>Scan</Text></View>
        <Pressable onPress={() => router.push("/profiles")} accessibilityRole="button" style={styles.tab}><Text style={styles.navIcon}>♟</Text><Text style={styles.navText}>Profile</Text></Pressable>
      </View>
      {createElement("input", {
        ref: fileRef,
        type: "file",
        accept: "image/jpeg,image/png",
        onChange: (event: ChangeEvent<HTMLInputElement>) => {
          const file = event.target.files?.[0];
          if (file) void acceptFile(file);
          event.target.value = "";
        },
        style: { display: "none" },
        "aria-label": "Choose a menu image",
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.white },
  content: { flexGrow: 1 },
  darkArea: { flex: 1, minHeight: 440, backgroundColor: "#101A16", alignItems: "center", paddingHorizontal: 18, paddingTop: 32, paddingBottom: 16 },
  restaurant: { color: colors.white, textAlign: "center", fontSize: 13, backgroundColor: "#2D3934", paddingVertical: 9, paddingHorizontal: 20, borderRadius: 22, overflow: "hidden", marginBottom: 24 },
  cameraFrame: { flex: 1, width: "100%", minHeight: 240, maxHeight: 590, overflow: "hidden", borderRadius: 18, borderWidth: 3, borderColor: colors.green, backgroundColor: "#13231D", justifyContent: "center" },
  camera: { width: "100%", height: "100%" },
  cameraFallback: { padding: 24, gap: 16 },
  cameraMessage: { color: colors.white, textAlign: "center", lineHeight: 22 },
  shutter: { height: 72, width: 72, borderRadius: 36, borderWidth: 4, borderColor: colors.white, alignSelf: "center", justifyContent: "center", alignItems: "center", marginTop: 26 },
  shutterInner: { width: 56, height: 56, borderRadius: 28, backgroundColor: colors.white },
  shutterDisabled: { opacity: 0.4 },
  navigation: { height: 72, flexDirection: "row", justifyContent: "space-around", alignItems: "center", backgroundColor: colors.white, borderTopWidth: 1, borderTopColor: colors.line },
  tab: { minWidth: 76, alignItems: "center", justifyContent: "center" },
  navIcon: { color: colors.muted, fontSize: 22, lineHeight: 23 },
  navIconSelected: { color: colors.green, fontSize: 22, lineHeight: 23 },
  navText: { color: colors.muted, fontSize: 12, marginTop: 2 },
  navSelected: { color: colors.green, fontWeight: "700", fontSize: 12, marginTop: 2 },
  error: { color: "#FFB4A9", marginTop: 10, lineHeight: 20, textAlign: "center" },
});
