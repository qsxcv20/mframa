# Mframa 项目交接文稿（截至 2026-10-19）

> 本文档面向接手者（人或 AI），读完应能独立继续开发、部署、答辩准备。
> 黑客松：TechHub Africa Hackathon 2026，赛道 Reducing Public Pollution，截止 2026-10-31。

---

## 1. 项目一句话

**Mframa**（契维语"风/空气"）：加纳阿克拉空气质量公众工具——网页端（Streamlit）+ 安卓 App，
用 OpenAQ 真实数据把 85 个监测站变成"我现在的空气能不能出门"的即时答案。

## 2. 关键资产与链接

| 资产 | 位置 |
|---|---|
| 线上网页（评委入口） | https://mframa.streamlit.app （Streamlit Cloud，自动部署 main 分支） |
| GitHub 仓库（公开） | https://github.com/qsxcv20/mframa |
| 本地工作目录 | `Q:\加纳地图环保` |
| 安卓 APK（最新） | `dist/Mframa-v0.7-debug.apk`（7.8MB，旧版 v0.1–v0.6 已删） |
| 安卓构建目录 | `C:\Users\yang2\mframa_build`（tar 同步源码后 assembleDebug） |
| Gradle | `C:\Users\yang2\gradle-dist\`（项目无 gradlew，用本机 Gradle 8.9） |
| 模拟器 | AVD 名 `tg`，adb：`C:/Users/yang2/Android/Sdk/platform-tools/adb.exe` |

**密钥纪律（绝不落盘提交）**：`OPENAQ_API_KEY`（Streamlit Secrets + 本地环境变量）、
`FIRMS_MAP_KEY`（GitHub Actions secret）、`TELEGRAM_BOT_TOKEN`（可选，未启用）。

## 3. 当前状态：已完成且验证通过

### 网页端（自检 20/20 全绿，线上实测正常）
- 四页结构：我的空气（健康档案+AQI 颜文字大卡+沙尘vs烟雾归因+香烟换算）、今日最佳时段、
  实时地图（85 站 IDW 热力场 + NASA FIRMS 火点层 + Agbogbloshie 90 天清运追踪卡）、
  更多（我吸入了什么 / 订阅空气提醒）
- 中英双语一键切换；手机/电脑自适应
- **推送（刚改版）**：浏览器通知 + 用户自设阈值滑块（15/25/35/55/75/100/150 µg/m³，
  默认 35=加纳 EPA 国标），localStorage 存储，零账号；托管环境拦截通知权限时
  降级为页面横幅+toast（文案如实说明）。Telegram/ntfy 界面已撤下
- demo 模式：`?demo=harmattan` 回放沙尘暴场景（演示兜底）
- 缓存与失败兜底：OpenAQ 抖动时回落本地快照 snapshot.json

### 安卓端（模拟器回归全过，logcat 零崩溃）
- WebView 壳 + 前台 GPS 暴露追踪（DoseLogic）+ 附近 280 家医院（geo 跳转已修）
- **本地阈值推送**：WorkManager 每 15 分钟拉 field.json，超用户阈值发系统通知（6h 冷却），
  关 App、重启手机照发
- **本地每日晨报**（刚加）：每天约 06:00 本机通知（今晨 PM2.5+AQI+建议），可独立开关；
  数据超 6h 未更新自动切换"停电夜发电机多，注意关窗"文案（模拟器实测命中弹出）
- 已修复的 P0：旋转/进程回收变砖、医院链接不跳（geo queries）、断网裸错误页（自定义离线页+重试）

### 数据管线（GitHub Actions，全部在跑）
- `alert_and_poll.yml`：15–30 分钟刷新 field.json + 每小时刷新快照 + 突发预警
- `morning_briefing.yml`：每日两发晨报（~05:45 & ~17:45 UTC）
- `fires.yml`：每 6 小时 NASA FIRMS 火点（已加防覆盖校验：空响应/格式变化不写好数据）
- 所有 CI push 已加 rebase+重试防冲突
- **隐私**：subscribers.json（Telegram chat_id）已移出 git 历史并 .gitignore

### 离线/停电容错（核心差异化，有 2026 当地报道背书）
- field.json（31×51 IDW 网格，raw.githubusercontent.com 分发）→ 安卓完全离线查询
- nowcast 引擎：站点离线时预测，12 算法泄漏-free 回测（n=684）+ 盲测 holdout，
  冠军 cand_regime2.py，MAE≈4.14 µg/m³（相对误差≈30%，朴素基线 42%）

## 4. 刚完成的三轮大改（详见 git log）

1. **六角色对抗排查+修复**（commit `b6af86d`）：4 P0 + 7 P1 + ~20 P2 全修，
   含安卓 3 P0、网页 None 数据兜底、HTML 注入防护、subscribers 隐私 P0
2. **三人调研团**（2026-10-19）：国情政策 / 民间声音 / 评委视角三份报告，
   关键发现见第 6 节
3. **推送体系纯本地化**（commit `4740d4c`）：网页浏览器通知 + 安卓本地晨报，
   Telegram/ntfy 降级为"可选技术储备"（CI 照跑，代码未删）

## 5. 验证命令

```bash
cd /q/加纳地图环保
python _selftest_app.py          # 网页自检，须 20/20 全绿
git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 pull --rebase origin main
git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 push origin main
```

- curl/git 需走代理 `http://127.0.0.1:7897`；adb shell 命令前加 `MSYS_NO_PATHCONV=1`
- **Streamlit 模块缓存坑**：push 后若线上显示裸 i18n key，touch i18n.py 尾部加注释强制全量重部署
- 验证线上页面用内置浏览器 `page.visual.snapshot`（text snapshot 读不到 iframe 内容）

## 6. 调研关键发现（README/答辩弹药，均有出处）

- 加纳 EPA 2026-06 官方承认：全国多数站点连本国 35 µg/m³ 标准都守不住，几乎全民暴露超标；
  每年约 2.8–3.2 万人死于空气污染，损失 25 亿美元/年（GDP 4.5%，世界银行）
- **停电 2026 依然严重**：7 月全国大停电；ECG 每周 7–9 小时分区停电表 → 离线容错是硬需求
- EPA 2026-01 专门澄清"当前霾是污染不是 Harmattan" → 沙尘vs烟雾归因是官方都没做好的差异化
- **金牌答辩故事**：Nima 市场卖粥母亲 Amina（MyJoy 2026-08-31）——"我能把他藏哪儿去？
  烟无处不在。" 她 9 岁儿子因咳嗽住院；同日实测 Nima 82 vs 富人区 Cantonments 12–19 µg/m³
- **差异化话术（重要）**：不能说"阿克拉没人做过"——Breathe Accra 已有 60 传感器。
  正确定位："他们建传感器网络，我们把数据变成每天两次推到你手机上的健康决策"
- 手机可行性：互联网普及率 69.8%，1GB 流量 $0.40；WhatsApp/Facebook 主导（Telegram 渗透低，
  这是推送改纯本地的依据）

## 7. 待办清单（按优先级，截止 10-31）

| # | 事项 | 状态 |
|---|---|---|
| 1 | **录 60 秒演示视频**（脚本已定稿，见下节） | ⬜ 未开始，最高优先 |
| 2 | 真机装 v0.7 APK 手测（下拉框/药丸按钮自动化测不了） | ⬜ 建议机主亲自做 |
| 3 | 调研成果写进 README（Amina 引语+EPA 声明+硬数字表） | ⬜ 素材齐，半天工作量 |
| 4 | 去掉安卓 WebView 底部 "Built with Streamlit" 底栏（需 Web 端配合） | ⬜ 可选 P2 |
| 5 | 答辩 PPT + 问答预案 | ⬜ 素材在调研报告里 |

### 60 秒视频脚本（已定稿，英文）
0:00–0:08 Amina 引语卡（黑底白字）→ 0:08–0:16 我的空气页 AQI 卡 →
0:16–0:26 地图 IDW 热力场+火点 → 0:26–0:36 最佳时段+归因卡（"nobody else in Accra answers that"）→
0:36–0:46 Agbogbloshie 清运追踪卡（"the data will speak"）→
0:46–0:56 安卓开飞行模式离线查询+通知弹出（高潮镜头，必实拍）→
0:56–1:00 标语卡 "Mframa — they built the sensors. We turn the data into your daily decision."

录法：Windows 自带 `Win+Alt+R` 录屏，网页+模拟器全在电脑上演示；分 6 段单独录；
剪映拼接+英文字幕；传 YouTube 不公开列出拿链接。配音可自念或 TTS。

## 8. 评分对照（当前自评 ~17.5–18/20）

- 设计与技术实现 (~4.5)：双端上线可演示，离线真实可用
- 技术复杂度 (~4.5)：nowcast 回测体系、IDW、field.json 管线、零依赖推送
- 潜在影响力 (~4.5)：国情背书强、可复制到其他非洲城市（改边界框+国家码）
- 创意 (~4.5)：香烟换算、归因卡、清运追踪卡、颜文字 AQI

## 9. 给接手者的三句话

1. **别动数据真实性红线**：OpenAQ key 走环境变量，demo 数据明确标注，失败兜底不许删。
2. **改 app.py 后必跑 `python _selftest_app.py` 保持全绿**；安卓改动后在模拟器回归旋转/断网/权限三场景。
3. 推送已是纯本地闭环，**不要再加需要用户注册/装第三方 App 的功能**——这是调研后的定案。


---

## 10. 2026-10-19 晚 进展（在第 1–9 节之后发生）

### A. 修复数据管线停摆（P0，已闭环）
- 现象：Alerts and Bot Poll 自 10-18 18:58 UTC 后停止，field.json 停在 18:27 UTC。
- 真正根因：commit b6af86d 在 alert_and_poll.yml 写了非法表达式
  `if: ${{ github.run_number % 4 == 1 }}`（GitHub Actions 表达式不支持 `%`），
  整个 workflow 解析失败，schedule 被注销；push 触发的运行表现为 0 jobs 秒失败。
- 修复：
  1. 取模判断移到 bash（`if [ $(( GITHUB_RUN_NUMBER % 4 )) -eq 1 ]`）—— commit 6a38c1f
  2. 三个会推 main 的 workflow（alert/fires/briefing）加共享并发组
     `concurrency.group: data-publish-${{ github.ref }}` 串行化 + 推送重试 5 次 + timeout —— 723a425
  3. workflow enable API 重新注册 schedule。
- 验证：手动 dispatch success；线上 field.json 刷新；随后 schedule 自动触发 success
  （GitHub 公共调度有 ~5 分钟延迟，正常）。现在每 15–30 分钟自动刷新。

### B. 新功能：按定位自动选最近监测站（网页 + 安卓双端，已上线）
- 网页（commit cce9110）：My Air / Best Hours 选站区新增 "📍 Use my location / 用我的定位"。
  - 浏览器 geolocation 取坐标 → 写 URL `?lat=&lon=` → Python 用 haversine 选最近站，
    显示"📍 Nearest monitor: X · about N km away"，并提供"恢复为市中心"。
  - 坐标只接受大阿克拉范围（USER_LOC_BBOX），域外拒绝，防手改 URL。
  - 新增文案在 i18n.py（geo_button/geo_hint/geo_located/geo_clear/geo_denied/geo_unavailable）。
  - 关键函数：parse_user_loc / haversine_km / nearest_index(stations,target) /
    geolocation_widget / pick_station（读 session_state["user_loc"]，三处选站自动生效）。
- 安卓（commit d654599，v0.8，versionCode 8）：AirQualityFragment 的 WebView 加
  setGeolocationEnabled + WebChromeClient.onGeolocationPermissionsShowPrompt，
  把网页定位请求映射到 Android 运行时权限（Manifest 里定位权限早已有）。
  新 APK：`dist/Mframa-v0.8-debug.apk`（7.7 MB；v0.7 已从 dist 删除，README 徽章改 v0.8）。
- Streamlit 缓存坑复现：push 后按钮一度显示裸 key "geo_button"（app.py 新但 i18n 旧），
  靠 commit 18f7ddc 给 i18n.py 加 cache-bust 注释强制全量重部署解决。**以后改 i18n 必带这步。**

### C. 验证
- `python _selftest_app.py`：21/21 全绿（新增用例
  "geolocation ?lat/lon auto-selects nearest station"，用 Nima Market 坐标断言）。
- AppTest 手测：?lat=5.5821&lon=-0.1986 → 自动选中 Nima Market，0.0 km。
- 安卓 v0.8 在 AVD tg 上 assembleDebug 成功、安装启动成功、新按钮出现；
  定位授权的完整点击流因模拟器在会话间退出未录屏，建议真机/重开模拟器点一次确认。

### D. 仍待办（沿用第 7 节，状态更新）
1. 60 秒演示视频 —— 仍最高优先，新增可拍镜头：点"Use my location"自动跳到最近站。
2. 真机手测 v0.8（重点：首次点定位的权限弹窗 → 选站 → 飞行模式离线）。
3. README 已补 Amina 之外的大部分调研数据；定位功能也已写进 Features。
   答辩 PPT + 问答预案仍未做。
4. Streamlit "Built with Streamlit" 底栏：安卓端 hideBadgeJs 已隐藏工具栏，
   但截图里底部 footer 仍在，可选 P2 再处理。

### E. 环境/命令备忘（本机）
- 自检必须带代理，否则页面内网络请求会挂起：
  PowerShell 里先 `$env:HTTPS_PROXY='http://127.0.0.1:7897'; $env:HTTP_PROXY=...` 再跑 python。
- git 走代理：`git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=... pull/push`；
  卡顿多为自动数据提交导致非 fast-forward，先 `git pull --rebase`（有未提交改动先 stash）。
- 安卓构建：源码在 `android/app`，构建目录 `C:\Users\yang2\mframa_build`（改完用 Copy-Item
  同步 .kt 和 build.gradle.kts），用 `C:\Users\yang2\gradle-dist\gradle-8.9\bin\gradle.bat
  assembleDebug`，产物 app/build/outputs/apk/debug/app-debug.apk 复制为 dist/Mframa-vX.X-debug.apk。
- 模拟器：AVD 名 tg；adb 在 C:/Users/yang2/Android/Sdk/platform-tools/adb.exe；
  模拟器进程可能随工具会话退出，掉了就重新 `emulator -avd tg` 再 wait-for-device。

