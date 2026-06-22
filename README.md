# TikTok iOS V2 大屏审核台

Mac + iPhone Mirroring 版审核控制台，适合大屏/外接屏窗口坐标。

## 第一次使用

1. 把仓库拉到本机，例如放到 `~/Desktop/tiktok-ios-v2-large-console`。
2. 复制配置模板：

   ```bash
   cp config.example.json config.json
   ```

3. 打开 `config.json`，填写自己的飞书表格配置：
   - `sheet.spreadsheet_token`
   - `sheet.sheet_id`
   - `sheet.current_row`
4. 双击 `一键准备并启动.command`。

一键脚本会检查鼠标宏组件、`lark-cli`、飞书授权和辅助功能权限；都通过后会启动 Web 审核台。

## 常用入口

- `一键准备并启动.command`：推荐入口。
- `检查环境.command`：只检查环境。
- `飞书授权.command`：只处理飞书授权。
- `直接启动审核控制台.command`：跳过准备步骤，直接启动。

## 不要提交

`config.json` 是本机配置，里面会有飞书表信息，不要提交到 GitLab。
