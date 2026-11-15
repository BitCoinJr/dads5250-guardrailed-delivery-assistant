# 非公開 Google スプレッドシートへの直接接続

MVP の **Google Sheets** は、Google Sheets API を使って、今回の案件台帳を直接読み込みます。CSV のダウンロードやアップロードは不要です。シートを公開したり、「リンクを知っている全員」に共有したりする必要もありません。

アプリは **読み取り専用**です。対象は今回の `Request backlog` タブの `A3:T200` に固定しています。BA の Go / Hold / Clarify はアプリのローカル監査記録に保存し、シートのセルや共有設定を書き換えません。

## 初回だけ行う設定

1. 自分の [Google Cloud Console](https://console.cloud.google.com/) で、この授業のデモ用プロジェクトを選ぶか作成します。
2. **API とサービス → ライブラリ**で **Google Sheets API** を有効にします。
3. **Google Auth platform** でアプリ情報を設定します。個人の Google アカウントなら対象を External とし、Testing のテストユーザーに自分のアカウントを登録します。組織の Workspace アカウントでは利用可能な設定や管理者の方針を確認してください。
4. **Clients → Create client → Desktop app** で OAuth クライアントを作成し、JSON をダウンロードします。Web application やサービスアカウントのキーは使用しません。
5. MVP フォルダの中に `.secrets` フォルダを作り、その JSON を `google_oauth_client.json` という名前で保存します。
6. MVP フォルダで次を実行します。

```powershell
.\.venv\Scripts\python.exe scripts\connect_google.py
```

ブラウザーで Google のログイン画面が開きます。対象シートを開ける自分のアカウントを選び、表示される権限を確認してログインを完了してください。ログインや同意は自分で操作します。アプリの画面更新だけでログイン画面が勝手に開くことはありません。

この接続は `spreadsheets.readonly` を要求します。Google の同意画面ではスプレッドシートの読み取り権限として表示されます。Google の OAuth スコープ自体は単一ファイル限定ではありませんが、この MVP の実装は指定した1つのシート ID と範囲だけを読みます。書き込み用スコープは要求しません。

接続に成功すると、ローカルの `.secrets/google_token.json` に次回用の認証情報が保存され、読み込めた案件数だけが表示されます。キー、トークン、シートの内容をターミナルへ表示しません。

## デモでの使い方

1. Google スプレッドシートで案件や BA メモを記入します。日付は `2026-11-18` のような ISO 形式にします。
2. MVP の BA intake で **Google Sheets** を選び、**Refresh Google Sheets** を実行します。
3. 取り込まれた内容を確認し、推薦理由を見て、人間が Go / Hold / Clarify を決めます。

相談前の初期起票では、Request ID・Request・Business requirement があれば読み込めます。BA がまだ評価していない Impact と Priority は空欄にして構いません。空欄の Impact は「未評価」のままで、3などの中間値を補いません。Priority は Unassigned、Effort は Unknown、BA status は New、BA decision は Pending として扱います。空欄以外の値は、所定の数値や選択肢に合わせてください。

Google 認証を設定する前は、明示的に区別された **Demo backlog** で画面や案件選定を確認できます。これは実シートの最新データを読み込んだ状態とは区別されます。

## 保存場所と接続の解除

`.secrets` フォルダは Git の追跡対象から除外しています。ダウンロードした JSON や認証情報をチャット、GitHub、提出用 ZIP、録画に含めないでください。

接続をやり直す場合はアプリを閉じ、ローカルの `google_token.json` を削除して接続スクリプトを再実行します。Google 側のアクセス許可は自分の Google アカウントの接続管理から解除できます。

対象シートを読み込めない場合は、ログインしたアカウント、シートへのアクセス権、Sheets API の有効化、OAuth のテストユーザー設定を確認します。エラー時にシートを公開へ変更する必要はありません。

公式資料: [Google Sheets Python quickstart](https://developers.google.com/workspace/sheets/api/quickstart/python)、[読み取り API](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/get)。
