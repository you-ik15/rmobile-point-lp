# rmobile-point.com 月次タイトル更新

[https://rmobile-point.com/](https://rmobile-point.com/) の `index.html` にある **【N月最新】** を、毎月月末の日本時間 23:00 ごろに翌月の数字へ更新します。

変わるのは次の 3 箇所だけです。

- `<title>`
- `<meta property="og:title">`
- `<meta name="twitter:title">`

例: 11月30日 → 【12月最新】、12月31日 → 【1月最新】。それ以外の文字、文字コード、改行は変えません。3 箇所以外のときは FTP へ送らず失敗します。すでに対象月なら何もしません。

転送は Xserver への平文 FTP（FTPS / SFTP ではない）です。ホスト `sv16829.xserver.jp`、ポート 21、パッシブモード。リモートパスの初期値は `/rmobile-point.com/public_html/index.html` です。

## シークレット

値はこのリポジトリに書きません。ワークフローも表示しません。

1. リポジトリの **Settings → Secrets and variables → Actions** を開く
2. **New repository secret** で次の 2 つを追加する

| Name | 内容 |
| --- | --- |
| `FTP_USERNAME` | Xserver の FTP ユーザー名 |
| `FTP_PASSWORD` | Xserver の FTP パスワード |

## 手動の dry run（最初はこちら）

本番の前に差分だけ確認します。アップロードも、`main` へのコミットもしません。

1. **Actions → Update monthly title → Run workflow**
2. `dry_run` は **true** のまま（初期値）
3. `target_month` は空欄でよいです。空欄のときは日本時間の翌月になります（11月中なら 12）。別の月を見たいときだけ 1〜12 を入れます
4. パスを変えて試すときだけ `remote_path` を指定します
5. 実行後、ジョブの Summary に更新前後の差分が出ます。Artifacts に取得したファイルと置換後のファイルが付きます

ファイルが無いときは、そのパスを明記して失敗します。`FTP_REMOTE_PATH`（ワークフロー先頭の `env`）か `remote_path` を直してください。

## 手動の本番実行

サイトをすぐ書き換えます。月の途中に空欄のまま本番実行すると、予定より早く翌月表示になります。スケジュールに任せる場合は、ここでは実行しないでください。

1. **Actions → Update monthly title → Run workflow**
2. `dry_run` を **false** にする
3. 必要なら `target_month` と `remote_path` を指定する

本番では次の順に動きます。

1. FTP で `index.html` を取得する
2. 取得したままのバイト列を `backup/index_YYYY-MM-DD_HHMM.html`（日本時間）に保存する。このファイルは編集しない
3. 【N月最新】を別のファイル上で置換し、差分を Summary に出す。3 箇所以外、またはすでに対象月のときは、ここで終わり、アップロードもコミットもしない
4. アップロードの直前に、同じ原本を artifact `backup-before-upload-...` にも残す
5. FTP でアップロードする
6. 同じパスを取り直して、送ったファイルとバイト単位で一致するか確認する
7. 一致したら、そのバックアップと更新後の `site/index.html` を `main` にコミットする

転送に失敗しても、artifact に原本が残っています。成功した実行では `backup/` にも同じ原本がコミットされます。

`main` へ GitHub Actions が push できる必要があります。ブランチ保護で Actions からの push を止めている場合は許可してください。

## 自動実行

cron は UTC なので `0 14 28-31 * *`（日本時間 23:00、毎月 28〜31 日）で起動します。日本時間で明日が 1 日のときだけ処理します。28 日や 29 日に起動しても、月末でなければ Summary に理由を書いて終了します。

定時実行が深夜 0 時（日本時間）を過ぎて遅延した場合は、この条件に合わずスキップされます。そのときは dry run で差分を見てから、`dry_run=false` で手動実行してください。

## バックアップから戻す

ワークフローは自動では戻しません。

1. 成功した実行なら、リポジトリの `backup/index_YYYY-MM-DD_HHMM.html` を開く。アップロードのあとで失敗している場合は、その実行の artifact `backup-before-upload-...` に入っている同名のファイルを使う
2. 中の 【N月最新】が戻したい月であることを確認する
3. FTP クライアントで次の設定で接続し、そのファイルを `index.html` として同じパスへ上書きする
   - ホスト: `sv16829.xserver.jp`
   - ポート: `21`
   - 暗号化: なし（平文 FTP）
   - パッシブモード: オン
   - ユーザー名とパスワード: 上記シークレットと同じもの
   - パス: `/rmobile-point.com/public_html/index.html`（変えている場合はそのパス）
4. ブラウザで [https://rmobile-point.com/](https://rmobile-point.com/) のタイトルを確認する

## ローカルテスト

`tests/fixtures/live_index.html` は、公開ページを HTTPS で取得した参考コピーです。FTP 上のファイルとバイト単位で同じとは限りません。本番は必ず FTP から取ったファイルを編集します。

```bash
python3 scripts/test_replace.py
```

プルリクエストでは workflow `Test month replacement` が同じテストを実行します。確認しているのは、参考コピーの 【11月最新】が 3 行だけ 【12月最新】になること、12 月→1 月、件数違いで失敗すること、月末判定です。
