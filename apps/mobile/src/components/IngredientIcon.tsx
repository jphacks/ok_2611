import { Image } from "react-native";
import { ingredientIconSources } from "../content/ingredientIconSources";

type Props = {
  allergenId: number;
  size: number;
};

export function IngredientIcon({ allergenId, size }: Props) {
  const source = ingredientIconSources[allergenId];
  if (!source) return null;
  return <Image source={source} style={{ width: size, height: size }} resizeMode="contain" accessible={false} />;
}
