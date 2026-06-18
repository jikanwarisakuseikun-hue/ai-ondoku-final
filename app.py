import streamlit as st
import azure.cognitiveservices.speech as speechsdk
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import os
import datetime

# --- 1. 画面の初期設定 ---
st.set_page_config(page_title="AI音読アドバイザー", layout="centered")
st.title("🗣️ AI音読アドバイザー")
st.write("英文を読んで、マイクで録音して提出しよう！")

# --- 2. 金庫（Secrets）から秘密の鍵を読み込む ---
try:
    AZURE_KEY_KISU = st.secrets["KEY_KISU"]
    AZURE_KEY_GUSU = st.secrets["KEY_GUSU"]
    AZURE_REGION = st.secrets["AZURE_REGION"]
    GOOGLE_DRIVE_FOLDER_ID = st.secrets["GOOGLE_DRIVE_FOLDER_ID"]
    GOOGLE_SHEET_ID = st.secrets["GOOGLE_SHEET_ID"]
    
    # Google認証情報の組み立て
    google_info = {
        "type": "service_account",
        "project_id": "ai-ondoku-final-go",
        "private_key_id": "dummy_id",
        "private_key": st.secrets["ROBOT_PRIVATE_KEY"],
        "client_email": st.secrets["ROBOT_EMAIL"],
        "client_id": st.secrets["ROBOT_CLIENT_ID"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{st.secrets['ROBOT_EMAIL']}"
    }
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = Credentials.from_service_account_info(google_info, scopes=scopes)
except Exception as e:
    st.error("🔑 金庫（Secrets）の設定が正しくありません。設定を確認してください。")
    st.stop()

# --- 3. 生徒の入力フォーム ---
st.subheader("📝 じょうほうを入力しよう")
col1, col2 = st.columns(2)
with col1:
    class_name = st.selectbox("クラス", ["1年1組", "1年2組", "1年3組"])
with col2:
    student_num = st.number_input("しゅっせきばんごう", min_value=1, max_value=40, value=1)

student_name = st.text_input("名前（ニックネームでもOK）")
unit_name = st.text_input("練習する単元（例: Unit 1）")
text_to_read = st.text_area("読む英文", "This is a pen.")

# --- 4. 録音とAI採点（セッション記憶対応） ---
st.subheader("🎙️ 録音して採点する")
audio_value = st.audio_input("マイクボタンを押して発音してね")

# 点数を一時保存する「記憶の部屋」を準備
if "saved_scores" not in st.session_state:
    st.session_state.saved_scores = None

if audio_value:
    # まだ採点データがない場合だけAzureを呼び出す
    if st.session_state.saved_scores is None:
        st.info("🤖 AIがあなたの発音を分析中...")
        
        # 音声ファイルを一時保存
        with open("temp_audio.wav", "wb") as f:
            f.write(audio_value.read())
            
        # 出席番号によるAzureキーの分散処理
        azure_key = AZURE_KEY_GUSU if student_num % 2 == 0 else AZURE_KEY_KISU
        speech_config = speechsdk.SpeechConfig(subscription=azure_key, region=AZURE_REGION)
        audio_config = speechsdk.audio.AudioConfig(filename="temp_audio.wav")
        
        # 発音評価の設定
        pron_config = speechsdk.PronunciationAssessmentConfig(
            reference_text=text_to_read,
            grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
            granularity=speechsdk.PronunciationAssessmentGranularity.Phoneme,
            enable_miscue=True
        )
        
        speech_recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
        pron_config.apply_to(speech_recognizer)
        result = speech_recognizer.recognize_once()
        
        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            pron_result = speechsdk.PronunciationAssessmentResult.from_result(result)
            
            # 点数をセッション状態にガッチリ記憶
            st.session_state.saved_scores = {
                "total": round(pron_result.pronunciation_score),
                "acc": round(pron_result.accuracy_score),
                "flu": round(pron_result.fluency_score),
                "pro": round(pron_result.prosody_score),
                "comp": round(pron_result.completeness_score)
            }

    # 記憶された点数がある場合は画面に固定表示
    if st.session_state.saved_scores:
        scores = st.session_state.saved_scores
        st.metric(label="総合点", value=f"{scores['total']} 点")
        st.write(f"🎯 正確さ: {scores['acc']} | 🌊 流暢さ: {scores['flu']} | 🎵 抑揚: {scores['pro']} | 🏁 完成度: {scores['comp']}")
        
        # --- 5. 提出ボタン ---
        if st.button("📤 先生に提出する", type="primary"):
            st.info("🚀 安全に提出中...")
            try:
                now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                filename = f"{class_name}_{student_num}_{student_name}_{unit_name}.wav"
                
                # Googleドライブへアップロード（共有ドライブ対応）
                drive_service = build('drive', 'v3', credentials=creds)
                file_metadata = {
                    'name': filename,
                    'parents': [GOOGLE_DRIVE_FOLDER_ID]
                }
                
                # ファイルが残っているか確認してアップロード
                if os.path.exists("temp_audio.wav"):
                    media = MediaFileUpload('temp_audio.wav', mimetype='audio/wav')
                    uploaded_file = drive_service.files().create(
                        body=file_metadata,
                        media_body=media,
                        fields='id, webViewLink',
                        supportsAllDrives=True
                    ).execute()
                    audio_link = uploaded_file.get('webViewLink')
                else:
                    audio_link = "音声ファイル未検出"
                
                # Googleスプレッドシートへデータ書き込み
                gc = gspread.authorize(creds)
                sheet = gc.open_by_key(GOOGLE_SHEET_ID).sheet1
                
                new_row = [
                    now, class_name, student_num, student_name, unit_name,
                    scores['total'], scores['acc'], scores['flu'], scores['pro'], scores['comp'], audio_link
                ]
                sheet.append_row(new_row)
                
                # 成功パフォーマンス（風船！）
                st.success("🎉 提出が完了しました！よくがんばったね！")
                st.balloons()
                
                # 次の提出のために記憶をリセット
                st.session_state.saved_scores = None
                if os.path.exists("temp_audio.wav"):
                    os.remove("temp_audio.wav")
                
            except Exception as e:
                st.error(f"❌ 提出中にエラーが発生しました。先生に報告してください。\nエラー詳細: {e}")
else:
    # 新しい録音がまだない、またはクリアされたら記憶をリセット
    st.session_state.saved_scores = None
    if os.path.exists("temp_audio.wav"):
        try:
            os.remove("temp_audio.wav")
        except:
            pass
