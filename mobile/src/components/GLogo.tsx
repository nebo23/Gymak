/**
 * §10.5 GLogo — the mark, sized by prop, from `assets/logo.png`. Never
 * recoloured, never stretched (`resizeMode="contain"`, no `tintColor`), with
 * a minimum 24 dp clear space around it.
 *
 * `assets/logo.png` is still the placeholder mark (see the T-11 task note) —
 * this component is built to the §10.5 contract against that file as-is.
 */
import { Image, View } from "react-native";

import { useI18n } from "../i18n";
import { space } from "../theme/tokens";

export interface GLogoProps {
  size: number;
  testID?: string;
}

export function GLogo({ size, testID }: GLogoProps) {
  const { t } = useI18n();

  return (
    <View style={{ padding: space[5] }} testID={testID}>
      <Image
        source={require("../../assets/logo.png")}
        style={{ width: size, height: size }}
        resizeMode="contain"
        accessibilityRole="image"
        accessibilityLabel={t("common.appName")}
      />
    </View>
  );
}
