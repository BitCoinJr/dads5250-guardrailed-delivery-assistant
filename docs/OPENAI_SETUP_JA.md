# OpenAI API の設定

推奨モデルは `gpt-6.1-sol` です。アカウントで利用可能なモデルに変更する場合は、Responses API と Structured Outputs に対応するモデルを指定してください。

## キーの発行と保存

1. [OpenAI Platform の API keys](https://platform.openai.com/api-keys) に自分のアカウントでログインします。
2. 今回の開発で使用するプロジェクトを選び、新しい API キーを作成します。キーの名前は `DADS5250 Final Project` などにします。アカウントで必要な利用設定・請求設定が済んでいることも確認します。
3. MVP フォルダの `.env` を自分のエディターで開きます。ファイルがない場合は `.env.example` をコピーして `.env` にします。
4. 空の `OPENAI_API_KEY=` の右側にキーを貼り付けて保存します。`OPENAI_MODEL=gpt-6.1-sol` はそのまま使用できます。
5. ブラウザーのデモ画面を更新し、画面左の Generation mode を **OpenAI API** に切り替えます。初回に空だったキーは、画面更新時に読み込まれます。既に設定されたキーの変更や環境変数の変更には、アプリの再起動が必要です。

```dotenv
OPENAI_API_KEY=ここに自分のキーを設定
OPENAI_MODEL=gpt-6.1-sol
```

この例の日本語部分をそのまま使わず、発行した実際のキーに置き換えます。

## Codex との共有方法

キー自体をチャットに貼る必要はありません。上記のローカルファイルに保存した後、チャットで「`.env` に設定しました。OpenAI 接続を確認してください」と知らせてください。接続確認ではキーを画面やログに出力せず、アプリが環境変数として読み込みます。

`.env` は Git と提出用 ZIP に含めません。画面録画にもキーが映らないよう、エディターを閉じてから録画します。

## 初回の確認

`sample_request.csv` の1件で **Prepare and validate** を実行し、OpenAI モードの実行記録として、チケット・取得根拠・変更案・検証結果が表示されることを確認します。その後に通常6件の評価を実行します。サンプルモードでの成功と実 API の成功は別々に記録します。

認証、モデル利用権限、利用枠、接続などの問題がある場合、サンプルモードへ自動的に切り替えず、失敗した実行として表示します。API 利用料はアカウント側で発生します。

公式資料: [Developer quickstart](https://developers.openai.com/api/docs/quickstart)、[API keys and service accounts](https://developers.openai.com/api/docs/guides/api-keys)、[GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol)。
