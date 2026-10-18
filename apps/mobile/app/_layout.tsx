import { Link, router, Stack, useGlobalSearchParams, usePathname } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { hasActiveAccountSession } from "../src/api/auth";
import { BrandLogo } from "../src/components/BrandLogo";
import { BottomNavigation, bottomNavigationHeight, getNavigationTab } from "../src/components/BottomNavigation";
import { CaptureProvider } from "../src/features/capture/CaptureContext";
import { claimFirstVisit } from "../src/features/onboarding/firstVisit";
import { Walkthrough } from "../src/features/onboarding/Walkthrough";
import { colors } from "../src/theme";

const headerHeight = 74;
// ①–④ are the only screens open without logging in. Every other route, including unknown ones, needs a session.
const publicPaths = new Set(["/", "/onboarding", "/register", "/login"]);

export default function RootLayout() {
  const [showTour, setShowTour] = useState<boolean | null>(null);
  const checkedVisit = useRef(false);
  const pathname = usePathname();
  const { lang } = useGlobalSearchParams<{ lang?: string | string[] }>();
  const tourLanguage = lang === "ja" ? "ja" : "en";
  const showHeader = showTour === false && pathname !== "/";
  const requiresLogin = !publicPaths.has(pathname);
  // The pathname whose login check passed. Until it matches, the screen stays covered so a direct URL never shows it.
  const [allowedPath, setAllowedPath] = useState<string | null>(null);
  const covered = showTour === false && requiresLogin && allowedPath !== pathname;
  const activeTab = showTour === false && !covered ? getNavigationTab(pathname) : null;

  useEffect(() => {
    // Avoid claiming a second visit when development Strict Mode replays effects.
    if (checkedVisit.current) return;
    checkedVisit.current = true;
    setShowTour(claimFirstVisit());
  }, []);

  useEffect(() => {
    if (showTour !== false || !requiresLogin) return;
    if (hasActiveAccountSession()) setAllowedPath(pathname);
    else router.replace("/login");
  }, [showTour, requiresLogin, pathname]);

  return (
    <CaptureProvider>
      {showHeader ? <header style={{
        position: "fixed", top: 0, left: 0, right: 0, zIndex: 10,
        height: headerHeight, boxSizing: "content-box",
        paddingTop: "env(safe-area-inset-top, 0px)",
        display: "flex", alignItems: "center", justifyContent: "center",
        backgroundColor: colors.white,
      }}>
        <Link href="/map" accessibilityLabel="Go to Map">
          <BrandLogo width={210} variant="header" />
        </Link>
      </header> : null}
      <main lang={showTour ? tourLanguage : undefined} style={{
        height: "100dvh", boxSizing: "border-box", overflow: "hidden",
        paddingTop: `calc(${showHeader ? headerHeight : 0}px + env(safe-area-inset-top, 0px))`,
        paddingBottom: `calc(${activeTab ? bottomNavigationHeight : 0}px + env(safe-area-inset-bottom, 0px))`,
        paddingLeft: "env(safe-area-inset-left, 0px)",
        paddingRight: "env(safe-area-inset-right, 0px)",
        display: "flex", flexDirection: "column", width: "100%", position: "relative",
        maxWidth: 440, margin: "0 auto", backgroundColor: colors.white,
      }}>
        {showTour === null ? (
          <div role="status" aria-label="Loading Meelyze+" style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <BrandLogo width={140} variant="header" />
          </div>
        ) : showTour ? (
          <Walkthrough language={tourLanguage} onFinish={() => setShowTour(false)} />
        ) : (
          <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.white } }} />
        )}
        {covered ? (
          <div role="status" aria-label="Checking login" style={{
            position: "absolute", inset: 0, zIndex: 5, display: "flex", alignItems: "center", justifyContent: "center",
            backgroundColor: colors.white,
          }}>
            <BrandLogo width={140} variant="header" />
          </div>
        ) : null}
      </main>
      {activeTab ? <BottomNavigation activeTab={activeTab} /> : null}
    </CaptureProvider>
  );
}
