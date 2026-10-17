import { useEffect, useRef, useState } from "react";
import { router, useLocalSearchParams } from "expo-router";
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { ApiError, getAccountId } from "../src/api/auth";
import { createConfirmation } from "../src/api/menus";
import { getMenuAnalysis } from "../src/features/capture/analysis";
import { getSelectedAllergenIds } from "../src/features/profile/selection";
import { saveConfirmationResult } from "../src/features/menu-results/confirmationResults";
import { okinawaMenuDemo } from "../src/features/menu-results/demo";
import { saveLocalConfirmation, type StaffAnswer } from "../src/features/menu-results/localConfirmations";
import { newRequestId } from "../src/features/menu-results/requestId";
import { getStaffPublishConsent, saveStaffPublishConsent } from "../src/features/menu-results/staffConsent";
import { colors } from "../src/theme";

const japaneseNames: Record<number, string> = {
  1: "卵", 2: "乳", 3: "小麦", 4: "えび", 5: "かに", 6: "そば", 7: "落花生", 8: "くるみ",
  9: "大豆", 10: "ごま", 11: "カシューナッツ", 12: "アーモンド", 13: "あわび", 14: "いか",
  15: "いくら", 16: "オレンジ", 17: "キウイフルーツ", 18: "牛肉", 19: "さけ", 20: "さば",
  21: "鶏肉", 22: "バナナ", 23: "豚肉", 24: "ピスタチオ", 25: "マカダミアナッツ",
  26: "もも", 27: "やまいも", 28: "りんご", 29: "ゼラチン",
};

// Order and wording follow docs/screens.md ⑬.
const choices: { answer: StaffAnswer; label: string }[] = [
  { answer: "contains", label: "含まれる" },
  { answer: "shared_utensils", label: "同じ料理器具を使っている" },
  { answer: "does_not_contain", label: "含まれない" },
  { answer: "unknown", label: "わからない" },
];

function saveErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return "回答を保存できませんでした。同じ内容でもう一度お試しください。";
  if (error.status === 410) return "解析の有効期限が切れたため保存できません。お客様に端末をお返しし、再撮影をお願いしてください。";
  if (error.code === "confirmation_limit_reached") return "このメニューの確認回数の上限に達しました。お客様に端末をお返しし、再撮影をお願いしてください。";
  if (error.status === 401 || error.status === 404) return "このメニューの回答は保存できません。お客様に端末をお返しください。";
  if (error.status === 409) return "送信内容を確認できませんでした。もう一度お選びください。";
  if (error.status === 422) return "回答内容を確認できませんでした。回答を見直してください。";
  return "通信に失敗しました。同じ内容でもう一度お試しください。";
}

export default function ConfirmScreen() {
  const { id, dish_id: dishId, demo } = useLocalSearchParams<{ id?: string; dish_id?: string; demo?: string }>();
  const isDemo = demo === "okinawa";
  const analysis = !isDemo && id ? getMenuAnalysis(id) : null;
  const menu = isDemo ? okinawaMenuDemo() : analysis;
  const dish = menu?.dishes.find((item) => item.dish_id === dishId);
  const selectedIds = isDemo ? [3, 23] : getSelectedAllergenIds();
  const questions = selectedIds.map((allergenId) => ({
    allergenId,
    name: japaneseNames[allergenId] || `項目 ${allergenId}`,
  }));
  const [answers, setAnswers] = useState<Record<number, StaffAnswer>>({});
  // One request_id per draft. Resending the same answers reuses it so the API can detect the replay.
  const [requestId, setRequestId] = useState(newRequestId);
  const [consentOpen, setConsentOpen] = useState(false);
  const [handback, setHandback] = useState(false);
  const [validating, setValidating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const finishTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (finishTimer.current) clearTimeout(finishTimer.current);
  }, []);
  const answered = questions.filter((item) => answers[item.allergenId]).length;
  const complete = questions.length > 0 && answered === questions.length;
  const locked = validating || saving || handback;
  const accountId = getAccountId();
  const previewConsent = isDemo || !accountId;
  const consentScope = isDemo ? "okinawa-preview-user" : accountId || "anonymous-preview-user";
  const resultRoute = menu && dish ? {
    pathname: "/result" as const,
    params: { id: menu.menu_id, dish_id: dish.dish_id, ...(isDemo ? { demo: "okinawa" } : {}) },
  } : null;

  const choose = (allergenId: number, answer: StaffAnswer) => {
    if (locked || answers[allergenId] === answer) return;
    setAnswers((current) => ({ ...current, [allergenId]: answer }));
    // Changed answers are a new draft; only an unchanged resend may reuse the previous request_id.
    setRequestId(newRequestId());
    setError("");
  };

  const finishDemo = (publishConsent: boolean, rememberConsent: boolean) => {
    if (!menu || !dish || !resultRoute || finishTimer.current) return;
    try {
      saveLocalConfirmation(menu, dish.dish_id, answers, questions.map((item) => item.allergenId), publishConsent);
      if (rememberConsent) saveStaffPublishConsent(consentScope, publishConsent, previewConsent);
      // Keep the modal over the underlying page until the button tap has ended.
      finishTimer.current = setTimeout(() => {
        finishTimer.current = null;
        setConsentOpen(false);
        router.replace(resultRoute);
      }, 180);
    } catch (cause) {
      setConsentOpen(false);
      setError(cause instanceof Error ? cause.message : "回答を保存できませんでした。");
    }
  };

  const finish = async (publishConsent: boolean, rememberConsent = false) => {
    if (!menu || !dish || !complete || saving || handback) return;
    if (isDemo) {
      finishDemo(publishConsent, rememberConsent);
      return;
    }
    if (!analysis) return;
    setSaving(true);
    setError("");
    try {
      const result = await createConfirmation(analysis.menu_id, analysis.analysis_token, {
        request_id: requestId,
        answers: questions.map((item) => ({ dish_id: dish.dish_id, allergen_id: item.allergenId, answer: answers[item.allergenId] })),
        dietary_answers: [],
        publish_consent: publishConsent,
        locale: "en",
      });
      saveConfirmationResult(analysis.menu_id, result);
      if (rememberConsent) saveStaffPublishConsent(consentScope, publishConsent, previewConsent);
      setConsentOpen(true);
      setHandback(true);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) setRequestId(newRequestId());
      setError(saveErrorMessage(cause));
    } finally {
      setSaving(false);
    }
  };

  const completeAnswers = async () => {
    if (!menu || !dish || !complete || locked) return;
    setValidating(true);
    setError("");
    try {
      const response = await fetch("/confirm-validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          demo: isDemo ? "okinawa" : undefined,
          menuId: menu.menu_id,
          dishId: dish.dish_id,
          menu: isDemo ? undefined : { ...menu, analysis_token: undefined },
          selectedAllergenIds: questions.map((item) => item.allergenId),
          answers: questions.map((item) => ({ allergen_id: item.allergenId, answer: answers[item.allergenId] })),
        }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null) as { error?: { message?: string } } | null;
        throw new Error(payload?.error?.message || "回答を確認できませんでした。");
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "回答を確認できませんでした。");
      return;
    } finally {
      setValidating(false);
    }
    const remembered = getStaffPublishConsent(consentScope, previewConsent);
    if (remembered === null) setConsentOpen(true);
    else void finish(remembered);
  };

  const returnToCustomer = () => {
    if (!resultRoute || finishTimer.current) return;
    finishTimer.current = setTimeout(() => {
      finishTimer.current = null;
      setConsentOpen(false);
      router.replace(resultRoute);
    }, 180);
  };

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.pageContent}>
      <View style={styles.staffHeader}><Text style={styles.staffHeaderText}>This screen is for restaurant staff</Text></View>
      <View style={styles.body}>
        <Text style={styles.heading}>アレルギーの確認のお願い</Text>

        {!dish || !menu || questions.length === 0 ? (
          <View style={styles.missing}>
            <Text style={styles.error}>確認対象の料理とアレルゲンを読み込めませんでした。</Text>
          </View>
        ) : (
          <>
            <Text style={styles.intro}>こちらのお客様は<Text style={styles.bold}>{questions.map((item) => item.name).join("・")}</Text>のアレルギーがあります。{"\n"}「<Text style={styles.bold}>{dish.name}</Text>」に、次の食材が含まれているか教えてください。</Text>
            <Text style={styles.help}>上から順に当てはまるものを1つ選んでください。原材料に含まれる→「含まれる」、原材料には含まれないが同じ料理器具を使っている→「同じ料理器具を使っている」、原材料に使っていないと確認できる→「含まれない」、いずれも確認できない→「わからない」。</Text>
            <Text style={styles.progress}>回答済み {answered} / {questions.length}</Text>

            {questions.map((question) => (
              <View key={question.allergenId} style={styles.question}>
                <Text style={styles.questionName}>この料理に{question.name}は含まれますか？</Text>
                <View style={styles.choiceGrid}>
                  {choices.map((choice) => {
                    const selected = answers[question.allergenId] === choice.answer;
                    return (
                      <Pressable
                        key={choice.answer}
                        accessibilityRole="radio"
                        accessibilityState={{ checked: selected, disabled: locked }}
                        accessibilityLabel={`${question.name}: ${choice.label}`}
                        disabled={locked}
                        onPress={() => choose(question.allergenId, choice.answer)}
                        style={[styles.choice, selected && styles.selectedChoice]}
                      >
                        <View style={[styles.radio, selected && styles.selectedRadio]}>{selected ? <Text style={styles.check}>✓</Text> : null}</View>
                        <Text style={styles.choiceLabel}>{choice.label}</Text>
                      </Pressable>
                    );
                  })}
                </View>
              </View>
            ))}

            {error && !consentOpen ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
            <View style={styles.spacer} />
            <Pressable accessibilityRole="button" disabled={!complete || locked} onPress={() => void completeAnswers()} style={[styles.finishButton, (!complete || locked) && styles.disabledButton]}>
              <Text style={styles.finishText}>{validating ? "回答を確認中…" : saving ? "保存中…" : "回答を終える"}</Text>
            </Pressable>
          </>
        )}
      </View>

      <Modal transparent animationType="fade" visible={consentOpen} onRequestClose={() => { if (!saving && !handback) setConsentOpen(false); }}>
        <View style={styles.modalShade}>
          {handback ? (
            <View style={styles.consentCard}>
              <Text style={styles.consentIcon}>✓</Text>
              <Text style={styles.consentTitle}>回答を保存しました</Text>
              <Text style={styles.consentText}>お客様に端末をお返しください</Text>
              <View style={styles.consentActions}>
                <Pressable accessibilityRole="button" style={[styles.consentAction, styles.agree]} onPress={returnToCustomer}><Text numberOfLines={1} style={styles.agreeText}>お客様に返す</Text></Pressable>
              </View>
            </View>
          ) : (
            <View style={styles.consentCard}>
              <Text style={styles.consentIcon}>✓</Text>
              <Text style={styles.consentTitle}>ご回答ありがとうございました</Text>
              <Text style={styles.consentText}>このメニュー情報と回答を、{"\n"}お店の情報として登録してもよろしいですか？{"\n"}次に来店するお客様の確認に役立ちます</Text>
              <Text style={styles.consentNote}>
                {menu?.google_place_id
                  ? "お客様が同意した場合のみ公開されます。同意しない場合も、回答は公開せずにこのお店の確認履歴の集計に使われます。"
                  : "店舗が選ばれていないため公開されません。"}
              </Text>
              {error ? <Text accessibilityRole="alert" style={[styles.error, styles.modalError]}>{error}</Text> : null}
              <View style={styles.consentActions}>
                <Pressable accessibilityRole="button" disabled={saving} style={[styles.consentAction, styles.decline, saving && styles.disabledButton]} onPress={() => void finish(false, true)}><Text numberOfLines={1} style={styles.declineText}>同意しない</Text></Pressable>
                <Pressable accessibilityRole="button" disabled={saving} style={[styles.consentAction, styles.agree, saving && styles.disabledButton]} onPress={() => void finish(true, true)}><Text numberOfLines={1} style={styles.agreeText}>{saving ? "保存中…" : "同意する"}</Text></Pressable>
              </View>
            </View>
          )}
        </View>
      </Modal>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.white },
  pageContent: { flexGrow: 1, backgroundColor: colors.white },
  staffHeader: { backgroundColor: colors.green, alignItems: "center", paddingTop: 20, paddingBottom: 20 },
  staffHeaderText: { color: colors.white, fontSize: 15, fontWeight: "700" },
  body: { flexGrow: 1, paddingHorizontal: 20, paddingTop: 24, paddingBottom: 24 },
  heading: { color: colors.ink, fontSize: 22, fontWeight: "800" },
  intro: { color: colors.ink, fontSize: 14, lineHeight: 23, marginTop: 14, marginBottom: 10 },
  bold: { fontWeight: "800" },
  help: { color: colors.muted, fontSize: 12, lineHeight: 18, marginBottom: 10 },
  progress: { color: colors.greenDark, fontSize: 13, fontWeight: "700", marginBottom: 12 },
  question: { borderWidth: 1.5, borderColor: colors.line, borderRadius: 19, padding: 12, marginBottom: 12 },
  questionName: { color: colors.ink, fontSize: 16, fontWeight: "800", marginBottom: 10 },
  choiceGrid: { flexDirection: "row", flexWrap: "wrap", columnGap: 8, rowGap: 8 },
  choice: { width: "48.8%", borderWidth: 1.5, borderColor: "#C8D8CF", borderRadius: 12, minHeight: 48, flexDirection: "row", alignItems: "center", paddingHorizontal: 8, gap: 5 },
  selectedChoice: { borderColor: colors.green, backgroundColor: colors.greenPale },
  radio: { width: 19, height: 19, borderRadius: 10, borderWidth: 1.5, borderColor: "#90A99D", alignItems: "center", justifyContent: "center" },
  selectedRadio: { backgroundColor: colors.green, borderColor: colors.green },
  check: { color: colors.white, fontSize: 12, fontWeight: "800", lineHeight: 15 },
  choiceLabel: { color: colors.ink, fontSize: 12, flexShrink: 1 },
  spacer: { flexGrow: 1, minHeight: 40 },
  finishButton: { backgroundColor: colors.green, borderRadius: 28, minHeight: 54, alignItems: "center", justifyContent: "center" },
  disabledButton: { opacity: 0.4 },
  finishText: { color: colors.white, fontSize: 16, fontWeight: "800" },
  missing: { marginTop: 24 },
  error: { color: colors.error, marginBottom: 12, fontSize: 13, lineHeight: 19 },
  modalError: { marginTop: 16, marginBottom: 0, textAlign: "center" },
  modalShade: { flex: 1, backgroundColor: "rgba(20,31,27,0.5)", alignItems: "center", justifyContent: "center", padding: 20 },
  consentCard: { width: "100%", maxWidth: 400, backgroundColor: colors.white, borderRadius: 25, padding: 24, alignItems: "center" },
  consentIcon: { color: colors.green, backgroundColor: colors.greenPale, fontSize: 24, fontWeight: "800", textAlign: "center", textAlignVertical: "center", width: 54, height: 54, lineHeight: 54, borderRadius: 17, overflow: "hidden" },
  consentTitle: { color: colors.ink, fontSize: 19, fontWeight: "800", marginTop: 20, textAlign: "center" },
  consentText: { color: colors.ink, fontSize: 13, lineHeight: 22, marginTop: 15, textAlign: "center" },
  consentNote: { color: colors.muted, fontSize: 12, lineHeight: 18, marginTop: 25, textAlign: "center" },
  consentActions: { width: "100%", flexDirection: "row", gap: 10, marginTop: 30 },
  consentAction: { flex: 1, minWidth: 0, minHeight: 52, borderRadius: 26, alignItems: "center", justifyContent: "center", paddingHorizontal: 8 },
  decline: { borderColor: colors.line, borderWidth: 1.5 },
  agree: { backgroundColor: colors.green },
  declineText: { color: colors.ink, fontWeight: "700" },
  agreeText: { color: colors.white, fontWeight: "700" },
});
