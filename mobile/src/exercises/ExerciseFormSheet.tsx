/**
 * Create / edit a user's own exercise -- the owner-authorised departure from spec §1.2.
 *
 * One sheet serves both modes because the fields are identical and the only differences
 * are the title, the submit label and which endpoint runs; two near-duplicate forms
 * would drift the moment a vocabulary gains a value.
 *
 * On the primitives this uses: GSheet hosts it, GTextInput takes the name and the
 * instructions, GChip rows take the four closed vocabularies, and GDialog (Part A)
 * confirms the destructive delete over on the detail screen. `GNumberField` is
 * deliberately NOT used -- a custom exercise has no numeric field for it to serve
 * (sets, reps and weight belong to a logged set, not to the exercise definition), and
 * forcing one in would invent a column the API does not have.
 *
 * The vocabularies come from api/exercises.ts, which mirrors the backend's own tuples --
 * the same tuples its CHECK constraints are built from. Each value renders through an
 * i18n key, so nothing user-visible is derived from the raw slug.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";

import { resolveErrorCode } from "../api/errors";
import {
  DIFFICULTIES,
  EQUIPMENT,
  MOVEMENT_PATTERNS,
  PRIMARY_MUSCLES,
  createExercise,
  updateExercise,
  type ExerciseDetailData,
} from "../api/exercises";
import { GButton, GChip, GErrorBanner, GSheet, GTextInput } from "../components";
import { useI18n } from "../i18n";
import { useTheme } from "../theme/useTheme";
import { textStyle } from "../theme/typography";
import { space } from "../theme/tokens";

export interface ExerciseFormSheetProps {
  visible: boolean;
  onClose: () => void;
  /** Absent = create. Present = edit that row. */
  initial?: ExerciseDetailData | null;
  onSaved: (exercise: ExerciseDetailData) => void;
  testID?: string;
}

const DEFAULT_MUSCLE = PRIMARY_MUSCLES[0];
const DEFAULT_EQUIPMENT = EQUIPMENT[0];
const DEFAULT_PATTERN = MOVEMENT_PATTERNS[0];
const DEFAULT_DIFFICULTY = DIFFICULTIES[0];

function ChoiceRow({
  labelText,
  values,
  selected,
  onSelect,
  labelFor,
  testIDPrefix,
}: {
  labelText: string;
  values: readonly string[];
  selected: string;
  onSelect: (value: string) => void;
  labelFor: (value: string) => string;
  testIDPrefix: string;
}) {
  const theme = useTheme();
  const { locale } = useI18n();
  return (
    <View style={styles.field}>
      <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
        {labelText}
      </Text>
      {/* Wraps rather than scrolls horizontally: seventeen muscles in a single scroll
          strip hides most of them behind a gesture, and at 130% font scale the labels
          are wide enough that a wrapped grid is the only layout that stays reachable. */}
      <View style={styles.chips}>
        {values.map((value) => (
          <GChip
            key={value}
            label={labelFor(value)}
            selected={selected === value}
            onPress={() => onSelect(value)}
            testID={`${testIDPrefix}-${value}`}
          />
        ))}
      </View>
    </View>
  );
}

export function ExerciseFormSheet({
  visible,
  onClose,
  initial,
  onSaved,
  testID,
}: ExerciseFormSheetProps) {
  const theme = useTheme();
  const { t, locale } = useI18n();
  const isEdit = initial != null;

  const [name, setName] = useState("");
  const [instructions, setInstructions] = useState("");
  const [muscle, setMuscle] = useState<string>(DEFAULT_MUSCLE);
  const [equipment, setEquipment] = useState<string>(DEFAULT_EQUIPMENT);
  const [pattern, setPattern] = useState<string>(DEFAULT_PATTERN);
  const [difficulty, setDifficulty] = useState<string>(DEFAULT_DIFFICULTY);
  const [isCompound, setIsCompound] = useState(false);
  const [saving, setSaving] = useState(false);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);

  // Re-seed every time the sheet opens: in edit mode from the row being edited, in
  // create mode back to the defaults, so a cancelled create never leaks its half-typed
  // values into the next one.
  useEffect(() => {
    if (!visible) return;
    setName(initial?.name ?? "");
    setInstructions(initial?.instructions ?? "");
    setMuscle(initial?.primary_muscle ?? DEFAULT_MUSCLE);
    setEquipment(initial?.equipment ?? DEFAULT_EQUIPMENT);
    setPattern(initial?.movement_pattern ?? DEFAULT_PATTERN);
    setDifficulty(initial?.difficulty ?? DEFAULT_DIFFICULTY);
    setIsCompound(initial?.is_compound ?? false);
    setErrorCode(null);
    setNameError(null);
    setSaving(false);
  }, [visible, initial]);

  const muscleLabel = useCallback((value: string) => t(`muscles.${value}`), [t]);
  const equipmentLabel = useCallback((value: string) => t(`equipment.${value}`), [t]);
  const patternLabel = useCallback((value: string) => t(`movementPatterns.${value}`), [t]);
  const difficultyLabel = useCallback((value: string) => t(`difficulty.${value}`), [t]);

  const trimmedName = useMemo(() => name.trim(), [name]);

  const handleSave = useCallback(async () => {
    if (trimmedName.length === 0) {
      setNameError(t("exercises.form.nameRequired"));
      return;
    }
    setNameError(null);
    setErrorCode(null);
    setSaving(true);
    try {
      const payload = {
        name: trimmedName,
        primary_muscle: muscle,
        equipment,
        movement_pattern: pattern,
        difficulty,
        is_compound: isCompound,
        instructions: instructions.trim(),
      };
      const response = isEdit
        ? await updateExercise(initial.id, payload)
        : await createExercise(payload);
      onSaved(response.exercise);
      onClose();
    } catch (error) {
      setErrorCode(resolveErrorCode(error));
    } finally {
      setSaving(false);
    }
  }, [
    trimmedName,
    muscle,
    equipment,
    pattern,
    difficulty,
    isCompound,
    instructions,
    isEdit,
    initial,
    onSaved,
    onClose,
    t,
  ]);

  return (
    <GSheet visible={visible} onClose={onClose} testID={testID}>
      <View style={styles.header}>
        <Text style={[textStyle("h3", locale), { color: theme.textPrimary }]}>
          {t(isEdit ? "exercises.form.editTitle" : "exercises.form.createTitle")}
        </Text>
        <GButton
          variant="ghost"
          label={t("common.cancel")}
          onPress={onClose}
          testID="exercise-form-cancel"
        />
      </View>

      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
      >
        {errorCode ? (
          <GErrorBanner code={errorCode} testID="exercise-form-error" />
        ) : null}

        <GTextInput
          label={t("exercises.form.nameLabel")}
          placeholder={t("exercises.form.namePlaceholder")}
          value={name}
          onChangeText={setName}
          error={nameError ?? undefined}
          testID="exercise-form-name"
        />

        {/* One name, one language. The server writes it to both name columns, so this
            exercise never renders blank after a language switch -- explained to the
            user rather than left as a surprise. */}
        <Text style={[textStyle("caption", locale), { color: theme.textMuted }]}>
          {t("exercises.form.nameHint")}
        </Text>

        <ChoiceRow
          labelText={t("exercises.detail.primaryMuscleLabel")}
          values={PRIMARY_MUSCLES}
          selected={muscle}
          onSelect={setMuscle}
          labelFor={muscleLabel}
          testIDPrefix="exercise-form-muscle"
        />
        <ChoiceRow
          labelText={t("exercises.detail.equipmentLabel")}
          values={EQUIPMENT}
          selected={equipment}
          onSelect={setEquipment}
          labelFor={equipmentLabel}
          testIDPrefix="exercise-form-equipment"
        />
        <ChoiceRow
          labelText={t("exercises.form.movementPatternLabel")}
          values={MOVEMENT_PATTERNS}
          selected={pattern}
          onSelect={setPattern}
          labelFor={patternLabel}
          testIDPrefix="exercise-form-pattern"
        />
        <ChoiceRow
          labelText={t("exercises.form.difficultyLabel")}
          values={DIFFICULTIES}
          selected={difficulty}
          onSelect={setDifficulty}
          labelFor={difficultyLabel}
          testIDPrefix="exercise-form-difficulty"
        />

        <View style={styles.field}>
          <Text style={[textStyle("label", locale), { color: theme.textSecondary }]}>
            {t("exercises.form.isCompoundLabel")}
          </Text>
          <View style={styles.chips}>
            <GChip
              label={t("common.no")}
              selected={!isCompound}
              onPress={() => setIsCompound(false)}
              testID="exercise-form-compound-no"
            />
            <GChip
              label={t("common.yes")}
              selected={isCompound}
              onPress={() => setIsCompound(true)}
              testID="exercise-form-compound-yes"
            />
          </View>
        </View>

        <GTextInput
          label={t("exercises.form.instructionsLabel")}
          placeholder={t("exercises.form.instructionsPlaceholder")}
          value={instructions}
          onChangeText={setInstructions}
          testID="exercise-form-instructions"
        />

        <GButton
          label={t(isEdit ? "exercises.form.save" : "exercises.form.create")}
          onPress={() => void handleSave()}
          loading={saving}
          disabled={saving}
          testID="exercise-form-submit"
        />
      </ScrollView>
    </GSheet>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: space[2],
  },
  scroll: {
    // A bounded height, not flex: the sheet sizes to its content, and an unbounded
    // ScrollView inside it collapses to zero on Android.
    maxHeight: 520,
  },
  content: {
    gap: space[3],
    paddingBottom: space[4],
  },
  field: {
    gap: space[1],
  },
  chips: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: space[1],
  },
});
