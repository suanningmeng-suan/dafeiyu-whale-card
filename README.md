## 下载（可直接用）

- **电脑版（Windows）**：[whale-card-desktop.zip](https://github.com/suanningmeng-suan/dafeiyu-whale-card/releases/download/v1.0.0/whale-card-desktop.zip) —— 解压后双击 `启动.bat`
- **手机版（安卓 10+）**：[whale-card-mobile.zip](https://github.com/suanningmeng-suan/dafeiyu-whale-card/releases/download/v1.0.0/whale-card-mobile.zip) —— 里面是 APK，覆盖安装即可

手机版 SHA-256：`93c3c642924ce2a526789c20225ed07251f3fdb6e3be7945f3be22d1f700df38`
# 传话纸 · 让机器人举牌子说话

把机器人要说的话，画成一张「角色举着纸 / 木牌」的图片发出去——字就写在纸上，
长句自动缩字号、按纸的形状换行、写不下就跳过。

给 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 用的插件，配合仓库里的独立渲染器开箱可用。

![效果](samples/01-happy.jpg)

## 它能做什么

- **按比例精准出图**：`rate` 设 10，就是每 100 句话里**恰好** 10 张。不是掷骰子，而是「进位记账」：每句加 rate/100 分，攒满 100 分才发一张，所以 `rate=30` 时按第 4、7、10… 句发，间隔稳定在 3~4 句，长期比例精确等于设置值
- **只发图 / 图文都发**：`mode = image` 时文字从消息里去掉，只留牌子（字已经在牌子上）
- **心情**：按语气猜——「好耶！」→ 开心，「为什么呀？」→ 不解，「算了……」→ 无语，
  猜不出来时在几个中性心情里随机，不会永远同一张脸
- **四种「能写字的地方」**：
  - `rows` 逐行宽度表：纸被手指挡住、越往下越窄时用
  - `pages` 书页流：摊开的笔记本，左页写满再写右页
  - `quad` 四点：举的是斜着的木牌/牌子，文字跟着板子倾斜（仿射，字不会一大一小）
  - 都不填：整张图随便写
- **该跳过的会跳过**：太长的（默认 28 字）、带链接的、不是中文的、已经在发表情包/图片/@人/@引用的消息，一律原样发，不画牌子

## 装法

1. 把这个仓库放进 AstrBot 的插件目录，确保目录名是 `astrbot_plugin_whale_card`：

   ```
   AstrBot/data/plugins/astrbot_plugin_whale_card/
   ```

2. 装依赖：`pip install pillow`（渲染器用它画字）

3. 准备素材（下面三步，任选一种模式）

   **A. 独立渲染模式（推荐先跑通）**

   - 把 `renderer/cards.example.json` 复制成 `renderer/cards.json`
   - 把 `renderer/font.ttf` 换成一个中文字体（默认读这个文件名；MiSans、思源黑体、微软雅黑都行）
   - 把角色的底图放进 `renderer/images/`，然后改 `cards.json` 里的路径和 `rows`/`quad`

   **B. 复用你已有的「传话纸」工程**

   - `config.json` 里填 `"project_dir": "D:/你的/传话纸工程"`，
     渲染就会走那套工程（字体、角色、可写区改完立刻生效）

4. 复制 `config.example.json` 成 `config.json`，按需改：

   ```json
   {
     "enabled": true,
     "rate": 10,          // 百分比：10 = 每百句正好十张（进位记账，不是随机）
     "mode": "image",     // image 只发图 / both 文字+图
     "role": "鲸鲸",       // cards.json 里的角色名
     "max_chars": 28,     // 超过就不画
     "auto_mood": true,   // 按语气猜心情
     "python": "",        // 留空用 AstrBot 自己的解释器；建议指向装了 Pillow 的那个
     "renderer": "renderer/render.py",
     "cards": "renderer/cards.json",
     "project_dir": ""
   }
   ```

5. 重启 AstrBot（插件改动不会热加载）。

## 怎么标「能写字的地方」

拿一张底图，量出纸上/牌子上能落笔的区域，写进 `cards.json`。

**矩形/梯形纸面**：给两三层 `(y, 左, 右)`，中间自动插值

```json
"rows": [[675, 298, 745], [790, 300, 745], [905, 316, 684]]
```

**摊开的书**：`pages` 两页，每页一套 `rows`；两页首行高度要写一样，字才不会跳

```json
"pages": [
  [[600, 320, 508], [760, 402, 508]],
  [[600, 532, 716], [760, 533, 652]]
]
```

**斜着的木牌**：写四个角，顺序是 左上、右上、右下、左下

```json
"quad": [[32, 200], [556, 46], [662, 352], [138, 607]],
"pad_x": 0.13,
"pad_y": 0.17
```

`pad_x / pad_y` 是四周留白（相对牌子的宽高），别贴边。

## 单独调用渲染器

```bash
echo '{"cards":"renderer/cards.json","role":"鲸鲸","expr":"#开心#","text":"今天也要好好吃饭呀","out":"out.png"}' | python renderer/render.py
# -> {"ok": true, "path": "..."}
```

## 日志

运行日志在 `astrbot_plugin_whale_card/cards.log.jsonl`（最多 500 条），
每条带 `kind`（send / skip / error）和原因，例如 `too-long:34`、`url`、`lang:cjk=0/28`。

## 已知边界

- 渲染走子进程 + Pillow，一张图 0.3–1.5 秒（1024×1024）；机器慢的时候别把 `rate` 开太高
- 心情是**猜**的，机器人不会主动告诉你它现在什么情绪；想要准的，得在它的回复里带心情标记
- 底图和字体请自备，注意版权

## 许可

MIT，见 [LICENSE](LICENSE)。
