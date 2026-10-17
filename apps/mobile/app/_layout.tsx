import { Stack, usePathname } from "expo-router";
import { BrandLogo } from "../src/components/BrandLogo";
import { CaptureProvider } from "../src/features/capture/CaptureContext";
import { colors } from "../src/theme";

const headerHeight = 74;

export default function RootLayout() {
  const showHeader = usePathname() !== "/";

  return (
    <CaptureProvider>
      {showHeader ? <header style={{
        position: "fixed", top: 0, left: 0, right: 0, zIndex: 10,
        height: headerHeight, boxSizing: "content-box",
        paddingTop: "env(safe-area-inset-top, 0px)",
        display: "flex", alignItems: "center", justifyContent: "center",
        backgroundColor: colors.white,
      }}>
        <BrandLogo width={140} variant="header" />
      </header> : null}
      <main style={{
        height: "100dvh", boxSizing: "border-box", overflow: "hidden",
        paddingTop: `calc(${showHeader ? headerHeight : 0}px + env(safe-area-inset-top, 0px))`,
        paddingBottom: "env(safe-area-inset-bottom, 0px)",
        paddingLeft: "env(safe-area-inset-left, 0px)",
        paddingRight: "env(safe-area-inset-right, 0px)",
        display: "flex", flexDirection: "column", width: "100%",
        maxWidth: 440, margin: "0 auto", backgroundColor: colors.white,
      }}>
        <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.white } }} />
      </main>
    </CaptureProvider>
  );
}
