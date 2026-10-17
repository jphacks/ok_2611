import { Image } from "react-native";

const icon = require("../../assets/meelyze-icon.webp");
const header = require("../../assets/meelyze-header.webp");

type BrandLogoProps = {
  width: number;
  variant?: "icon" | "header";
};

export function BrandLogo({ width, variant = "icon" }: BrandLogoProps) {
  const isHeader = variant === "header";
  return (
    <Image
      accessibilityLabel="Meelyze+ logo"
      source={isHeader ? header : icon}
      resizeMode="contain"
      style={{ width, height: isHeader ? width * (50 / 140) : width }}
    />
  );
}
