import { router } from "expo-router";
import { colors } from "../theme";

export const bottomNavigationHeight = 72;
type NavigationTab = "map" | "scan" | "profile";

const tabs = [
  { id: "map", label: "Map", href: "/map" },
  { id: "scan", label: "Scan", href: "/capture" },
  { id: "profile", label: "Profile", href: "/profiles" },
] as const;

export function getNavigationTab(pathname: string): NavigationTab | null {
  switch (pathname) {
    case "/map": return "map";
    case "/capture":
    case "/menu": return "scan";
    case "/profiles":
    case "/profiles/edit": return "profile";
    default: return null;
  }
}

function NavigationIcon({ tab }: { tab: NavigationTab }) {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {tab === "map" ? <><path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3Z" /><path d="M9 3v15M15 6v15" /></> : null}
      {tab === "scan" ? <><path d="M8 6 10 3h4l2 3h4a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1Z" /><circle cx="12" cy="12" r="4" /></> : null}
      {tab === "profile" ? <><circle cx="12" cy="7" r="4" /><path d="M4 21v-2a8 8 0 0 1 16 0v2" /></> : null}
    </svg>
  );
}

export function BottomNavigation({ activeTab }: { activeTab: NavigationTab }) {
  return (
    <nav aria-label="Main navigation" style={{
      position: "fixed", bottom: 0, left: 0, right: 0, zIndex: 10,
      width: "100%", maxWidth: 440, margin: "0 auto", boxSizing: "border-box",
      height: `calc(${bottomNavigationHeight}px + env(safe-area-inset-bottom, 0px))`,
      paddingBottom: "env(safe-area-inset-bottom, 0px)",
      paddingLeft: "env(safe-area-inset-left, 0px)",
      paddingRight: "env(safe-area-inset-right, 0px)",
      display: "flex", backgroundColor: colors.white, borderTop: `1px solid ${colors.line}`,
    }}>
      {tabs.map((tab) => (
        <button key={tab.id} type="button" aria-current={activeTab === tab.id ? "page" : undefined}
          onClick={() => router.navigate(tab.href)} style={{
            flex: 1, minWidth: 0, border: 0, background: "transparent", cursor: "pointer",
            display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 4,
            color: activeTab === tab.id ? colors.green : colors.muted,
            fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
            fontSize: 12, lineHeight: "16px", fontWeight: activeTab === tab.id ? 700 : 400,
          }}>
          <NavigationIcon tab={tab.id} />
          <span>{tab.label}</span>
        </button>
      ))}
    </nav>
  );
}
