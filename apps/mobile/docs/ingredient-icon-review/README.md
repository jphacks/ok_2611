# Ingredient icon review

The application assets live in `../../assets/ingredient-icons/`. That folder
contains exactly 29 individual SVG files, named with lowercase ingredient
names. Every SVG uses `viewBox="0 0 128 128"` and a white background.
Black fills are used only for pistachio, salmon roe, beef, and crab; the other
icons use black outlines and white interiors.

Sixteen icons were adapted from the user-provided free images: wheat, walnut,
peanut, cashew, beef, buckwheat, almond, salmon roe, banana, chicken,
macadamia nut, salmon, shrimp, squid, yam, and crab. Their visible boundaries
were traced as SVG paths; black filled areas were converted to white except
for the four ingredients named above.
The remaining icons are original line drawings. The SVGs contain no English
labels or embedded titles; translated names belong to the application UI.

`index.html` and `contact-sheet.png` are review files. They are deliberately
outside the asset folder so each asset can be retrieved by its filename.
`order.json` records the requested order: nine required ingredients, followed
by 20 recommended ingredients. The mobile selection list already uses this
same order.

The menu screens use these SVGs through `src/content/ingredientIconSources.ts`.
After changing an SVG, run `node scripts/build-ingredient-icon-sources.mjs`
from `apps/mobile` to refresh the bundled sources.
