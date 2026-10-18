import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const iconDirectory = join(root, "assets", "ingredient-icons");
const output = join(root, "src", "content", "ingredientIconSources.ts");

// IDs match allergenOptions in src/content/preferences.ts.
const icons = [
  [1, "egg"], [2, "milk"], [3, "wheat"], [6, "buckwheat"], [7, "peanut"],
  [4, "shrimp"], [5, "crab"], [8, "walnut"], [11, "cashew"],
  [12, "almond"], [13, "abalone"], [14, "squid"], [15, "salmon-roe"],
  [16, "orange"], [17, "kiwi-fruit"], [18, "beef"], [10, "sesame"],
  [19, "salmon"], [20, "mackerel"], [9, "soy"], [21, "chicken"],
  [22, "banana"], [23, "pork"], [24, "pistachio"], [25, "macadamia-nut"],
  [26, "peach"], [27, "yam"], [28, "apple"], [29, "gelatin"],
];

const files = readdirSync(iconDirectory).sort();
const expected = icons.map(([, name]) => `${name}.svg`).sort();
if (JSON.stringify(files) !== JSON.stringify(expected)) {
  throw new Error("Ingredient icon folder must contain exactly the 29 mapped SVG files.");
}

const rows = icons.map(([id, name]) => {
  const base64 = readFileSync(join(iconDirectory, `${name}.svg`)).toString("base64");
  return `  ${id}: { uri: "data:image/svg+xml;base64,${base64}" },`;
});

writeFileSync(output, `// Generated from assets/ingredient-icons/*.svg by scripts/build-ingredient-icon-sources.mjs.\n` +
  `// Edit the SVG files, then rerun the script. Keep labels in the UI, not in SVGs.\n` +
  `export const ingredientIconSources: Readonly<Record<number, { uri: string }>> = {\n` +
  rows.join("\n") + `\n};\n`);
