[한국어](./README.md) | [English](./README_EN.md) | **日本語** | [中文](./README_ZH.md)

# AI Professor Lite

> Version `1.0.0`

AI Professor Liteは、講義企画、スライド、音声、教授アバター動画、最終MP4の生成、Moodleへの配布までを一つの流れで処理するセルフホスト型の講義制作アプリケーションです。

FastAPIベースのWeb UIとSQLiteジョブキューを使用し、メディア生成のような重い処理はGPUごとに独立したrunnerで実行します。OpenAIは講義構成、画像、TTS、参考資料RAGに使用し、Ditto TalkingHeadは教授アバター動画の生成に使用します。

## 画面と生成例

ダッシュボードでは、接続状態、生成中の講義、Dittoエンジンの状態、最近のジョブを一目で確認できます。

<p align="center">
  <img src="docs/images/dashboard.png" alt="AI Professor Lite ダッシュボード" width="100%">
</p>

講義詳細画面では現在の生成stageと進捗を確認でき、完了後はPPTX、最終講義MP4、narration WAV、Quiz JSONなどの成果物をダウンロードできます。デスクトップとモバイルUIの両方に対応しています。

<table>
  <tr>
    <td width="72%"><img src="docs/images/lecture-progress-desktop.png" alt="講義生成進捗画面 - デスクトップ"></td>
    <td width="28%"><img src="docs/images/lecture-progress-mobile.png" alt="講義生成進捗画面 - モバイル"></td>
  </tr>
  <tr>
    <td align="center"><sub>デスクトップ講義詳細 / 生成進捗</sub></td>
    <td align="center"><sub>モバイル講義詳細</sub></td>
  </tr>
</table>

### 実際の講義動画生成フロー

AI Professor Liteは、生成したPPT/スライド、TTS音声（`narration.wav`）、教授画像をもとに生成したDitto TalkingHeadをFFmpegで合成し、最終講義動画`final_lecture.mp4`を生成します。

<table>
  <tr>
    <td width="52%"><img src="docs/images/generated-slide.png" alt="生成された講義スライド例"></td>
    <td width="14%" align="center"><img src="docs/images/narration-wav.png" alt="narration.wav 音声" width="120"></td>
    <td width="34%"><img src="docs/images/professor-avatar-source.png" alt="TalkingHead生成に使用する教授画像"></td>
  </tr>
  <tr>
    <td align="center"><sub>PPT / 生成された講義スライド</sub></td>
    <td align="center"><sub><code>narration.wav</code></sub></td>
    <td align="center"><sub>Ditto TalkingHead用教授画像</sub></td>
  </tr>
</table>

<p align="center"><strong>PPT / スライド + 音声 + TalkingHead → <code>final_lecture.mp4</code></strong></p>

<p align="center">
  <img src="docs/images/final-lecture-preview.png" alt="PPTとTalkingHeadを合成した最終講義動画フレーム" width="100%">
</p>

<p align="center"><sub>実際の最終講義動画フレーム例 — スライドとTalkingHeadが一つの動画に合成されます。</sub></p>

> リポジトリにはREADME用の静止画像例のみを含みます。実際に生成されたMP4やWAVなどの大容量成果物は、アプリケーションの講義詳細画面で管理します。

---

## 主な機能

- 会員登録 / ログインとユーザーごとのデータ分離
- 韓国語 / 英語 / 日本語 / 中国語UI
- ブラウザ言語の自動検出とユーザー言語の固定
- ユーザーごとのOpenAI BYOK、またはサーバー共通API Key
- PDF / TXT / Markdown / DOCX / PPTX参考資料
- 参考資料全文入力、またはembeddingベースRAG
- 講義案、スライド構成、narration、Quiz生成
- GPT Imageベースのスライド画像生成
- PowerPoint（`.pptx`）および1920×1080スライドPNG生成
- OpenAI TTSベースの講義音声生成
- 目標講義時間に合わせたnarration自動補強
- Ditto TalkingHeadベースの教授アバター動画生成
- 背景除去 / chroma key前処理
- FFmpegベースの最終講義MP4合成
- PPT確認後の承認 / 修正 / 再開
- Moodle course / section / VideoTracker連携
- AI Instructorによる学期単位の自動講義生成と予約公開
- SQLite lease queue、retry、heartbeat、checkpoint復旧
- 複数GPU worker
- ユーザーごとのOpenAI使用量確認

---

## 要件

### Dockerインストール

- Linux
- Docker Engine
- NVIDIA Driver
- NVIDIA Container Toolkit
- Git
- Git LFS
- OpenSSL
- NVIDIA GPU

ホスト上で次の2つのコマンドが正常に実行できる必要があります。

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

### 手動インストール

- Linux / POSIX環境
- Python 3.10
- FFmpeg / FFprobe
- NVIDIA GPU + CUDA / TensorRT環境
- SQLite

アプリケーションとDittoは同じPython 3.10環境で実行します。

---

## クイックスタート

### Dockerインストール

Dockerインストールは`setup.sh`または`setup_en.sh`を基準にします。

```bash
git clone <REPOSITORY_URL>
cd ai_prof_lite

chmod +x setup.sh
./setup.sh
```

英語版インストールスクリプト:

```bash
chmod +x setup_en.sh
./setup_en.sh
```

Dockerの詳細インストール、手動インストール、環境変数、GPU/Worker設定、データとセキュリティ、トラブルシューティングについては[`docs/INSTALLATION_JA.md`](./docs/INSTALLATION_JA.md)を参照してください。

---

## 初期設定

1. アカウントを作成します。
2. プロフィールで基本言語を選択します。
3. `API / 接続設定`でOpenAI credentialを登録します。
4. Moodleを使用する場合は、Moodle Web Service情報を登録します。
5. 新しい講義を作成し、必要に応じて参考資料を添付します。
6. PPT確認段階でスライドを確認し、承認します。
7. 生成完了後、PPTX、動画、音声、Quiz JSONなどの成果物をダウンロードします。
8. Moodle接続が設定されている場合はVideoTrackerに公開できます。

---

## ドキュメント

- [インストールと運用](./docs/INSTALLATION_JA.md)
- [開発者ガイド](./docs/DEVELOPMENT_JA.md)
- [コントリビュート](./CONTRIBUTING_JA.md)

---

## Moodle

Moodle連携ではユーザーごとのWeb Service credentialを使用します。

対応フロー:

- course照会
- section照会
- VideoTracker照会
- 既存activityへの動画接続
- 新しいVideoTracker activityの作成
- 講義完了後の即時公開
- AI Instructorによる予約公開

Moodleを使用しなくても講義生成機能は動作します。

---

## AI Instructor

AI Instructorは学期スケジュールに合わせて講義を自動で企画し、生成ジョブを予約する機能です。

主な機能:

- 担当Moodle courseの選択
- 講義スケジュール計算
- 教授アバター管理
- 予定講義の自動生成
- 失敗 / 中断状態の追跡
- Moodle予約公開
- サーバー再起動後のcatch-up

復旧許容時間:

```env
AI_INSTRUCTOR_CATCHUP_GRACE_MINUTES=120
```

---

## サポート

バグ報告や機能提案はGitHub Issuesを利用してください。

---

## プロジェクトとコントリビューター

AI Professor Liteは**学生主導で開発されたオープンソースプロジェクト**です。開発過程では技術的な助言とプロジェクト支援を受けています。

### 現在のコントリビューター

| 名前 | GitHub | 役割 |
|---|---|---|
| **Iamjunseok** | [@Iamjunseok](https://github.com/Iamjunseok) | 開発者 / Collaborator |
| **Wonyoung Choi** | [@waitinghm-creator](https://github.com/waitinghm-creator) | 開発者 / Collaborator |
| **ChunCheon Man** | [@hero707](https://github.com/hero707) | 技術アドバイザー / プロジェクト支援 |
| **hallymgitoslab** | @hallymgitoslab | プロジェクト支援 / Contributor |

---

## 支援・謝辞

本成果物は、2026年度教育部および江原特別自治道の財源により江原ANCHORセンターの支援を受けて実施された地域成長人材養成体系（ANCHOR）グローカル大学30の成果です。(2026-ANCHOR-10-009)

**English acknowledgement**

This research was supported by the ANCHOR program(Glocal University30) through the Gangwon ANCHOR Center, funded by the Ministry of Education(MOE) and the Gangwon State(G.S.),Republic of Korea.(2026-ANCHOR-10-009)

---

## ライセンス

Apache License 2.0。ライセンス全文は[`LICENSE`](./LICENSE)を参照してください。
