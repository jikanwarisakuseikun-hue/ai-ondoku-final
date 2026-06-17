import streamlit as st
import azure.cognitiveservices.speech as speechsdk
import os
import io
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import pandas as pd

st.set_page_config(page_title="AI音読アドバイザー Max Pro", layout="centered")
st.title("🗣️ AI音読システム（成績表＆音声自動提出）")
st.write("録音して点数を確認したら、「先生に提出する」ボタンを押してください。")

# --- 1. アカウント＆負荷分散スイッチ ---
attendance_type = st.radio(
    "あなたの 出席番号（または班） を選んでください：",
    ["奇数番号 (1, 3, 5...)", "偶数番号 (2, 4, 6...)"],
    horizontal=True
)

if "奇数" in attendance_type:
    azure_key = st.secrets["KEY_KISU"]
else:
    azure_key = st.secrets["KEY_GUSU"]

azure_region = st.secrets["AZURE_REGION"]

# --- 2. 生徒の個人情報入力 ---
col1, col2, col3 = st.columns(3)
with col1:
    class_name = st.text_input("クラス：", placeholder="例: 1組")
with col2:
    student_num = st.text_input("出席番号：", placeholder="例: 05")
with col3:
    student_name = st.text_input("イニシャル：", placeholder="例: TS")

unit_name = st.text_input("学習する単元（今日練習する場所）：", placeholder="例: U1 Part1")
reference_text = st.text_input("練習する英文（教科書の英語を入力してね）：", placeholder="例: Welcome to our school.")

st.markdown("---")
st.subheader("🎤 録音スタート")
audio_value = st.audio_input("マイクボタンを押して英語を読んでね")

if audio_value:
    st.info("AIが発音を多角的に分析中... 🤖")
    
    audio_bytes = audio_value.read()
    with open("temp_audio.wav", "wb") as f:
        f.write(audio_bytes)
        
    try:
        speech_config = speechsdk.SpeechConfig(subscription=azure_key, region=azure_region)
        audio_config = speechsdk.audio.AudioConfig(filename="temp_audio.wav")
        
        pronunciation_config = speechsdk.PronunciationAssessmentConfig(
            json_string=f'{{"referenceText":"{reference_text}","gradingSystem":"HundredMark","granularity":"Word","phonemeAlphabet":"IPA"}}'
        )
        pronunciation_config.enable_prosody_assessment()
        
        speech_recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
        pronunciation_config.apply_to(speech_recognizer)
        result = speech_recognizer.recognize_once_async().get()
        
        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            pron_result = speechsdk.PronunciationAssessmentResult(result)
            
            score_acc = int(pron_result.accuracy_score)
            score_flu = int(pron_result.fluency_score)
            score_comp = int(pron_result.completeness_score)
            score_pros = int(pron_result.prosody_score) if hasattr(pron_result, 'prosody_score') else 85
            
            final_score = int((score_acc + score_flu + score_pros + score_comp) / 4)
            
            st.success(f"🎉 総合スコア: {final_score} 点 / 100点")
            
            st.markdown("### 📈 あなたの発音ステータス（観点別）")
            chart_data = pd.DataFrame({
                "観点": ["正確さ(音)", "流暢さ(スピード)", "抑揚(リズム)", "完成度(読み飛ばし)"],
                "スコア": [score_acc, score_flu, score_pros, score_comp]
            })
            st.bar_chart(chart_data.set_index("観点"))
            
            colored_words = []
            for word in pron_result.words:
                if word.error_type == "None":
                    colored_words.append(f":green[{word.word}]")
                elif word.error_type == "Mispronunciation":
                    colored_words.append(f":red[{word.word}]")
                elif word.error_type == "Omission":
                    colored_words.append(f"~~{word.word}~~")
            st.subheader(" ".join(colored_words))
            
            st.markdown("---")
            st.subheader("📮 先生への自動提出")
            
            if not (class_name and student_num and student_name and unit_name and reference_text):
                st.warning("⚠️ 提出するには、クラス・出席番号・氏名・単元・英文をすべて入力してください。")
            else:
                if st.button("📤 この結果と音声を先生に提出する", type="primary"):
                    with st.spinner("先生のGoogle Driveへ送信中... 🚀"):
                        try:
                            robot_email = st.secrets["ROBOT_EMAIL"]
                            client_id = st.secrets["ROBOT_CLIENT_ID"]
                            formatted_private_key = st.secrets["ROBOT_PRIVATE_KEY"]
                            
                            info = {
                                "type": "service_account",
                                "project_id": "ai-ondoku-final-go",
                                "private_key_id": "google_cloud_key",
                                "private_key": formatted_private_key,
                                "client_email": robot_email,
                                "client_id": client_id,
                                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                                "token_uri": "https://oauth2.googleapis.com/token",
                                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs"
                            }
                            
                            creds = service_account.Credentials.from_service_account_info(
                                info, 
                                scopes=[
                                    "https://www.googleapis.com/auth/drive.file",
                                    "https://www.googleapis.com/auth/spreadsheets"
                                ]
                            )
                            drive_service = build('drive', 'v3', credentials=creds)
                            sheets_service = build('sheets', 'v4', credentials=creds)
                            
                            folder_id = st.secrets["GOOGLE_DRIVE_FOLDER_ID"]
                            spreadsheet_id = st.secrets["GOOGLE_SHEET_ID"]
                            
                            filename = f"{class_name}_{student_num}番_{student_name}_{unit_name}_{final_score}点.wav"
                            file_metadata = {
                                'name': filename,
                                'parents': [folder_id],
                                'description': f"総合点:{final_score}, 正確さ:{score_acc}, 流暢さ:{score_flu}, 抑揚:{score_pros}, 完成度:{score_comp}"
                            }
                            media = MediaIoBaseUpload(io.BytesIO(audio_bytes), mimetype='audio/wav')
                            
                            # 🌟 ロボット自身の容量ではなく、先生の共有フォルダの容量を使う設定（supportsAllDrives=True）を追加しました！
                            uploaded_file = drive_service.files().create(
                                body=file_metadata, 
                                media_body=media, 
                                fields='id',
                                supportsAllDrives=True
                            ).execute()
                            file_id = uploaded_file.get('id')
                            
                            audio_link = f"https://drive.google.com/file/d/{file_id}/view?usp=drivesdk"
                            
                            now_jst = datetime.utcnow() + timedelta(hours=9)
                            timestamp = now_jst.strftime('%Y-%m-%d %H:%M:%S')
                            
                            row_data = [
                                timestamp,
                                class_name,
                                student_num,
                                student_name,
                                unit_name,
                                final_score,
                                score_acc,
                                score_flu,
                                score_pros,
                                score_comp,
                                audio_link
                            ]
                            
                            body = {'values': [row_data]}
                            sheets_service.spreadsheets().values().append(
                                spreadsheetId=spreadsheet_id,
                                range="シート1!A:K",
                                valueInputOption="USER_ENTERED",
                                insertDataOption="INSERT_ROWS",
                                body=body
                            ).execute()
                            
                            st.balloons()
                            st.success("🎉 提出が完了しました！")
                            
                        except Exception as google_error:
                            st.error(f"❌ Googleシステムへの送信に失敗しました: {google_error}")
            
        else:
            st.error("AIがうまく声を聴き取れませんでした。もう一度試してね。")
    except Exception as e:
        st.error(f"❌ エラーが発生しました: {e}")
    finally:
        if os.path.exists("temp_audio.wav"):
            os.remove("temp_audio.wav")
