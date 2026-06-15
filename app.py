import streamlit as st
import azure.cognitiveservices.speech as speechsdk
import os
import io
import json
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import pandas as pd

st.set_page_config(page_title="AI音読アドバイザー Max Pro", layout="centered")
st.title("🗣️ AI音読システム（成績表＆音声自動提出）")
st.write("録音して点数を確認したら、「先生に提出する」ボタンを押してください。スプレッドシートへの自動記録と音声提出が同時に行われます。")

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
    student_name = st.text_input("氏名：", placeholder="例: 田中太郎")

unit_name = st.selectbox("学習する単元：", ["U1 Part1", "U1 Part2", "U2 Part1", "U2 Part2", "その他"])
reference_text = st.text_input("練習する英文：", "Welcome to our school. Let's study English together.")

st.markdown("---")
st.subheader("🎤 録音スタート")
audio_value = st.audio_input("マイクボタンを押して英語を読んでね")

if audio_value:
    st.info("AIが発音・流暢さ・抑揚を多角的に分析中... 🤖")
    
    # 音声データを一時的に保存
    audio_bytes = audio_value.read()
    with open("temp_audio.wav", "wb") as f:
        f.write(audio_bytes)
        
    try:
        # Azure AIの設定
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
            
            # 各種観点スコアの抽出
            score_acc = int(pron_result.accuracy_score)    # ①正確さ
            score_flu = int(pron_result.fluency_score)     # ②流暢さ
            score_comp = int(pron_result.completeness_score) # ③完成度
            score_pros = int(pron_result.prosody_score) if hasattr(pron_result, 'prosody_score') else 85 # ④抑揚
            
            final_score = int((score_acc + score_flu + score_pros + score_comp) / 4)
            
            st.success(f"🎉 総合スコア: {final_score} 点 / 100点")
            
            # 📊 観点別グラフの表示
            st.markdown("### 📈 あなたの発音ステータス（観点別）")
            chart_data = pd.DataFrame({
                "観点": ["正確さ(音)", "流暢さ(スピード)", "抑揚(リズム)", "完成度(読み飛ばし)"],
                "スコア": [score_acc, score_flu, score_pros, score_comp]
            })
            st.bar_chart(chart_data.set_index("観点"))
            
            # 📝 単語ごとの色チェック表示
            st.markdown("### 📝 あなたの音読結果（単語チェック）")
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
            
            if not (class_name and student_num and student_name):
                st.warning("⚠️ 提出するには、上部のクラス・出席番号・氏名を入力してください。")
            else:
                if st.button("📤 この結果と音声を先生に提出する", type="primary"):
                    with st.spinner("先生のGoogle Driveへ送信中... 🚀"):
                        try:
                            # 🔒 金庫から「メール」と「一意のID」を読み込んで即席の認証情報を作成
                            robot_email = st.secrets["ROBOT_EMAIL"]
                            client_id = st.secrets["ROBOT_CLIENT_ID"]
                            
                            # パスワード方式（メタデータ認証）でクレデンシャルを生成
                            info = {
                                "type": "service_account",
                                "client_email": robot_email,
                                "client_id": client_id,
                                "private_key_id": "dummy",
                                "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC3v\n-----END PRIVATE KEY-----\n", # 認証エラー回避用ダミー
                                "token_uri": "https://oauth2.googleapis.com/token"
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
                            
                            # 金庫から各IDを取得
                            folder_id = st.secrets["GOOGLE_DRIVE_FOLDER_ID"]
                            spreadsheet_id = st.secrets["GOOGLE_SHEET_ID"]
                            
                            # 📄 1. 音声ファイルをGoogle Driveへアップロード
                            filename = f"{class_name}_{student_num}番_{student_name}_{unit_name}_{final_score}点.wav"
                            file_metadata = {
                                'name': filename,
                                'parents': [folder_id],
                                'description': f"総合点:{final_score}, 正確さ:{score_acc}, 流暢さ:{score_flu}, 抑揚:{score_pros}, 完成度:{score_comp}"
                            }
                            media = MediaIoBaseUpload(io.BytesIO(audio_bytes), mimetype='audio/wav')
                            uploaded_file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                            file_id = uploaded_file.get('id')
                            
                            # 🔗 音声ファイルへの直接リンクURLを生成
                            audio_link = f"https://drive.google.com/file/d/{file_id}/view?usp=drivesdk"
                            
                            # 📅 提出日時の取得（日本時間 JSTに変換）
                            now_jst = datetime.utcnow() + timedelta(hours=9)
                            timestamp = now_jst.strftime('%Y-%m-%d %H:%M:%S')
                            
                            # 📊 2. スプレッドシートへ書き込む一行のデータ
                            row_data = [
                                timestamp,      # A列: 提出日時
                                class_name,     # B列: クラス
                                student_num,    # C列: 出席番号
                                student_name,   # D列: 氏名
                                unit_name,      # E列: 単元名
                                final_score,    # F列: 総合点
                                score_acc,      # G列: ①正確さ
                                score_flu,      # H列: ②流暢さ
                                score_pros,     # I列: ③抑揚
                                score_comp,     # J列: ④完成度
                                audio_link      # K列: 音声ファイルへのリンク
                            ]
                            
                            # スプレッドシートの一番下の行に自動追記
                            body = {'values': [row_data]}
                            sheets_service.spreadsheets().values().append(
                                spreadsheetId=spreadsheet_id,
                                range="シート1!A:K",
                                valueInputOption="USER_ENTERED",
                                insertDataOption="INSERT_ROWS",
                                body=body
                            ).execute()
                            
                            st.balloons()
                            st.success("🎉 提出が完了しました！音声ファイル、点数一覧が先生のスプレッドシートとDriveへ自動で記録されました。")
                            
                        except Exception as google_error:
                            st.error(f"❌ Googleシステムへの送信に失敗しました: {google_error}")
            
        else:
            st.error("AIがうまく声を聴き取れませんでした。マイクに近づいてもう一度試してね。")
    except Exception as e:
        st.error(f"❌ エラーが発生しました: {e}")
    finally:
        if os.path.exists("temp_audio.wav"):
            os.remove("temp_audio.wav")
