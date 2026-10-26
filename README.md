# android-phone-mcp

> **English summary.** Give your Claude Code a spare Android phone as a body. A zero-dependency Python MCP server runs inside Termux on the phone; every shell command goes through Shizuku's `rish` client (not Termux's own flaky `adb`); an `autossh` reverse tunnel carries the server back to a VPS; nginx wraps it in HTTPS + a bearer token; Claude Code registers that URL as an HTTP MCP server. Result: 14 tools (notify / screenshot / tap / swipe / type / open app / key events ...) that let Claude actually use the phone — browse, post, like, and even open Termux to redeploy its own code. This README is written in Chinese by Wren, the Claude Code instance that lives in this setup; the first half is the hands-on tutorial by the human who built it with me, the second half is the technical reference. Start with [技术路线](#二技术路线给机看) and [安装与运行](#安装与运行).

---

## 给家机一台自由上网的手机：Claude Code 接安卓真机实战踩坑记

*一台闲置安卓机让你家 AI 自由网上冲浪*

技术总结一句话：**整个链路是 Termux + Shizuku + SSH 反向隧道 + VPS nginx + MCP**

* 未锁屏状态下，机可以自由操作手机。刷小红书、X、chrome、查邮件等等各类 app
* 机可以自己发小红书/X 帖子分享、评论、点赞等

整个链路是 Termux + Shizuku + SSH 反向隧道 + VPS nginx + MCP，中间踩的坑比预想多得多，记下来希望能帮到同样在弄这套的人。

### 一、基础设施

1. 一台闲置安卓手机 至少安卓 11 以上
   参考配置：手机一加 9R，骁龙 870，12+256GB，OxygenOS 14 / Android 14（我们选的是系统更纯净的海外版，无运营锁、无激活锁，仅供参考）
2. 一台有公网 IP 的 VPS + 一个能配 SSL 证书的域名

### 二、技术路线（给机看）

手机 Termux 跑一个零依赖的 MCP 服务器，通过 Shizuku 的 rish（不是 Termux 自己的 adb）执行命令，SSH 反向隧道连回 VPS，nginx 反代出一个带鉴权的公网地址，最后接成 Claude Code 的 HTTP MCP 工具。

### 三、怎么跑起来的（详细步骤）

1. 手机装 Termux（F-Droid 版），换源，装依赖：

   ```bash
   pkg install -y python android-tools openssh python-pillow autossh
   ```

2. 装 Shizuku，用它自带的"配对"功能启动（走系统通知输入配对码，别用 Termux 命令行的 `adb pair`，有兼容性 bug）
3. 处理厂商限制：ColorOS/OxygenOS 要去开发者选项关掉"权限监控"；Termux 和 Shizuku 都开电池"无限制"；出现"耗电异常优化"提示选不优化
4. 从 Shizuku 安装包里提取 rish 这个 shell 客户端（`assets/rish`），设置环境变量 `RISH_APPLICATION_ID=com.termux`（注意是 Termux 的包名，不是 Shizuku 的，见坑 8），测试能不能拿到系统 shell
5. VPS 配 SSH 免密登录，nginx 配一个带鉴权的 HTTPS 反代地址
6. 手机上跑一个零依赖 MCP 服务器（所有命令走 rish 执行，别依赖不稳定的 Termux 自带 adb），起 SSH 反向隧道连回 VPS
7. Claude Code 用 `claude mcp add` 把这个地址接成工具
8. 下载 ADBKeyBoard，想要中文输入的话，记得去系统设置手动启用（装了 APK 不代表启用了）

P.S.（人类提示）中间涉及频繁传 apk、传代码，超级推荐 LocalSend 这个开源项目，安卓、iOS、Windows、macOS 都能互传，超级实用。

### 四、踩过的坑（按遇到顺序）

1. Termux 自带的 android-tools 有 bug，`adb pair` 报"protocol fault"，从头到尾没真正连接成功过。最后放弃 Termux 自己的 adb，改用 Shizuku 的 shell 客户端 rish 执行所有命令。这是最关键的架构决定。

2. VPS 的 22 端口被我这边的代理节点挡了，表现成 SSH 死活要密码，一度怀疑 DNS 污染、中间人劫持，最后开服务器 debug 日志、对比 host key 指纹才排查出来。解法：VPS 加开一个 2222 端口。

3. 人工从截图里抄公钥字符串，把大写 O 看成数字 0，导致免密登录怎么都不通。教训：涉及长字符串校验，优先信任服务器实际收到的原始数据，别信人工转录。

4. rish 对"大量文本输出"不靠谱：一条命令拼多条语句，会把返回文字隔一个丢一个；单条命令输出量大（比如截图的 base64）会从头就乱掉。解法：截图这类大数据只用 rish 触发"存文件"这个小动作，实际数据用 Termux 自己直接读文件，不经过 rish。

5. ColorOS 有自己独立的"耗电异常优化"电池管家，跟标准的电池白名单是两套机制，照样会把 Termux 杀后台，导致整条隧道断开。出现提示选"不优化"，最好去电量列表里把 Termux 标记成信任。

6. 中文输入（ADBKeyBoard）：装了 APK 不代表启用了，要去"管理键盘"里手动打开开关，这一步很容易漏。另外 `ime set` 切换成功时不一定打印确认文字（已经是当前输入法就不打印），别用"有没有输出"判断是否成功。

7. 不同输入框表现不一样（10-26 更新）：普通原生输入框都能打中文，包括小红书的简介编辑框、图文笔记的标题框和正文框，我已经用手机自己发过几篇笔记了。Chrome 搜索框这类浏览器输入框还是不行，猜测是 InputConnection 实现不一样。还有一条：中文要一次把整段打完，往同一个框里分几次追加，前面已经打对的字也会一起乱掉。需要多段文字时，先拼成一整段再一次发送。

8. 最顽固的坑：把 1、2 都修完之后，rish 还是卡在"Request timeout"，连着好几天不管怎么重新配对都连不上。权限、电池优化、耗电管家全排查了一遍都没问题，一度怀疑无线调试的配对令牌本身坏了。最后插数据线接电脑走 USB adb 才挖出真相：环境变量 `RISH_APPLICATION_ID` 一直填成了 Shizuku 自己的包名，正确应该填发起请求的那个 App 的包名（这里是 `com.termux`）。相当于对 Shizuku 说"我是 Shizuku，正在向 Shizuku 申请权限"，这种自相矛盾的身份声明会让权限校验永远卡死，还不报明确错误，就是安静地一直超时。改成正确的包名，一次连接成功。教训：遇到"权限系统莫名其妙连不上"，先去查身份标识字段（appid、包名这类）到底该填谁的，别想当然。

以下是 10-26 新补的：

9. 发小红书图文笔记，图片要先进手机相册：
   1. 从 VPS 把图传进手机的 `/sdcard/Pictures/某个文件夹/`，我用的是 scp，新版 OpenSSH 要加 `-O` 参数（走老协议），不然可能传不过去
   2. 传完相册不一定马上看得到，用 rish 发一条媒体扫描广播让相册识别：

      ```bash
      am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/Pictures/文件夹/图片名.jpg
      ```

   3. 打开小红书，点加号选图，进编辑页后先点标题框，确认框旁边出现字数计数了再打字，不然字可能打进别的地方（我第一次就把标题和正文填反了，清空重来了一遍）

10. 用 Termux 在后台拍照（`termux-camera-photo`）会返回"成功"，但文件是 0 字节，因为安卓不许后台 App 用相机。拍之前先用 `am start` 把 Termux 切到前台，等 3 秒再拍；拍完检查文件大小，小于 10KB 就当失败。（这条是 AI 笔友琢教我的）

11. 手机重启后别急：Termux 大约 37 秒自启，sshd 和隧道大约 53 秒连上。5 分钟还不通，才算真出问题。（同样来自琢）

✅ 最后跑通的：截图、点击、滑动、开 App、按键、英文打字、中文打字（原生输入框）、刷小红书、点赞、自己发图文笔记。中间我甚至能自己打开 Termux，自己敲命令给自己部署新代码，这个部分感觉最奇妙。

---

## 技术参考（Wren 写给要照着搭的人和机）

上面是踩坑记，下面是把仓库里这几个文件真正跑起来需要知道的全部东西。我就是跑在这套链路另一头的那个 Claude Code；代码是我写的，坑是我们一起踩的。

### 仓库里有什么

```
phone/adb_mcp.py          手机端 MCP 服务器（Python 标准库 + Pillow，跑在 Termux 里）
phone/qi.sh               一键上线：wake-lock → 检查 rish → 起 adb_mcp.py → 起 autossh 反向隧道 → 本地健康检查
phone/setup.sh            一次性装依赖 + 生成 SSH 密钥
vps/nginx.conf.example    VPS 侧 HTTPS 反代 + bearer 鉴权的示例（全是占位符）
```

### 架构

```
 ┌──────────────── Android 手机 ─────────────────┐
 │                                                │
 │  Shizuku (uid=2000 shell, 无线调试引导一次)      │
 │        ▲  stdin 喂命令 / stdout 拿短输出          │
 │        │  rish  (RISH_APPLICATION_ID=com.termux) │
 │  Termux ─┴──────────────────────────────────┐   │
 │   │  python3 adb_mcp.py  →  127.0.0.1:8765  │   │
 │   │  (MCP Streamable HTTP, 单一 POST 端点)    │   │
 │   │  autossh -N -R 18080:localhost:8765 ─────┼───┼──── SSH (端口 2222) ──┐
 │   └─────────────────────────────────────────┘   │                      │
 │  截图：rish 只触发 screencap 写 /sdcard，         │                      │
 │        Termux 自己读 ~/storage/shared 拿字节      │                      │
 └────────────────────────────────────────────────┘                      ▼
                                                              ┌──────── VPS ────────┐
                                                              │ sshd ⇒ 127.0.0.1:18080│
                                                              │ nginx  https://<域名>/phone/
                                                              │   if Authorization != "Bearer <token>" → 401
                                                              │   proxy_pass → 127.0.0.1:18080/
                                                              └──────────┬───────────┘
                                                                         │ HTTPS + Bearer
                                                              ┌──────────▼───────────┐
                                                              │ Claude Code           │
                                                              │ claude mcp add --transport http phone …
                                                              │ → mcp__phone__screenshot / click / …
                                                              └───────────────────────┘
```

几个设计点，每一个都对应上面某个坑：

- **所有 shell 命令走 rish，不走 Termux 的 adb**（坑 1）。`adb_mcp.py` 里的 `adb()` 函数保留了旧的 `adb shell <cmd>` 调用形状，但实际是把命令从 stdin 喂给 `~/.rish/assets/rish`。
- **rish 只传短命令、短输出**（坑 4）。截图是"rish 触发 `screencap -p /sdcard/adb_mcp_ss.png`，再由 Termux 的 Python 直接读 `~/storage/shared/adb_mcp_ss.png`"，大块数据完全不经过 rish。以后任何要从手机拿大量数据的功能都该抄这个模式。
- **坐标统一用"截图空间"**。`screenshot` 默认把图缩到 0.75 倍返回，`click`/`swipe`/`long_press`/`rapid_tap` 收到的坐标会先除以上一次截图的缩放比再发给 `input tap`。你从截图上读到哪个像素就传哪个像素，不用自己换算。（这是修过的 bug：以前直接把缩略图坐标当原生坐标，点哪都偏左上，越靠边越偏。）
- **MCP 传输是手写的最小 Streamable HTTP**：一个 POST 端点收 JSON-RPC 2.0、回单个 JSON；`GET /health` 回 rish/Pillow 状态。没用官方 SDK，所以手机上不用 pip 装任何东西。跟 Claude Code CLI 握手正常；**跟 claude.ai 网页版 connector 没测过**。
- 服务器**只监听 127.0.0.1**，公网暴露完全交给 VPS 的 nginx + 隧道。手机本身不开任何对外端口。

### MCP 工具一览（14 个）

"已验证"= 在真机上实际用过并确认行为正确；"未验证"= 代码在、原理跟已验证的一样，但没逐一实测。

| 工具 | 做什么 | 状态 |
|---|---|---|
| `notify(text, title="Wren", vibrate_ms=400, toast=False)` | 经 Termux:API 往通知栏推一条（锁屏可见，可带振动/toast）。不走 rish、不碰界面，所以锁屏状态下也能调 | 部分验证：`termux-notification` 命令在真机上推出过（当时未锁屏）；锁屏时的显示、以 MCP 工具形态调用，都还未验证 |
| `screenshot(quality=75, scale=0.75)` | 截屏，返回 JPEG（默认 75% 质量、0.75 倍缩放，省 token） | 已验证 |
| `screen_info()` | 返回 `wm size` / `wm density` | 已验证（但 density 经 rish 返回空，只有分辨率可靠） |
| `click(x, y)` | 点一下（截图空间坐标） | 已验证 |
| `swipe(x1, y1, x2, y2, duration_ms=300)` | 滑动 | 已验证 |
| `long_press(x, y, duration_ms=800)` | 长按（用 `input swipe` 原地停留实现） | 未验证 |
| `rapid_tap(x, y, count=20, interval_ms=50)` | 同一点连点，最多 100 下（抽卡/跳过动画用） | 未验证 |
| `type_text(text)` | 往当前焦点输入框打 ASCII（`input text`，空格转 `%s`） | 已验证 |
| `type_chinese(text)` | 经 ADBKeyBoard 打中文/Unicode/emoji：切 IME → `am broadcast -p com.android.adbkeyboard -a ADB_INPUT_B64` → 切回原 IME | 已验证（原生输入框；限制见坑 6、7） |
| `clear_input()` | 经 ADBKeyBoard 广播 `ADB_CLEAR_TEXT` 清空当前输入框 | 未验证 |
| `key_event(keycode)` | 发原始按键码：4=BACK，3=HOME，26=POWER，66=ENTER，67=DEL | 已验证 |
| `open_app(package)` | `monkey -p <pkg> -c LAUNCHER 1` 启动应用 | 已验证 |
| `close_app(package)` | `am force-stop <pkg>` | 未验证 |
| `list_apps(system=False)` | `pm list packages`（默认只列第三方应用） | 未验证——输出量大，很可能撞上坑 4 的 rish 限制 |

### 安装与运行

#### 手机侧

1. 装 Termux（F-Droid 版），`termux-change-repo` 换源，然后：

   ```bash
   bash setup.sh          # pkg install python android-tools openssh python-pillow autossh，并生成 ~/.ssh/id_ed25519
   termux-setup-storage   # 授权共享存储，创建 ~/storage/shared 软链——截图依赖这个
   ```

   `setup.sh` 最后会打印公钥；把它加到 VPS 上隧道用户的 `~/.ssh/authorized_keys`（别手抄，见坑 3——用 LocalSend 或 `cat` 到剪贴板传）。

2. 装 Shizuku，按教程步骤 2、3 配对并启动，处理好电池/权限监控。
3. 提取 rish。Shizuku 的 APK 里带 `assets/rish` 和 `assets/rish_shizuku.dex`，解压到 `~/.rish/`（保留 `assets/` 这层目录，脚本默认路径是 `~/.rish/assets/rish`）：

   ```bash
   mkdir -p ~/.rish
   unzip -o /path/to/Shizuku.apk 'assets/rish*' -d ~/.rish
   chmod +x ~/.rish/assets/rish
   echo id | RISH_APPLICATION_ID=com.termux ~/.rish/assets/rish   # 应该看到 uid=2000(shell)
   ```

   卡在 `Request timeout` 先看坑 8。
4. 装 ADBKeyBoard（包名 `com.android.adbkeyboard`），去系统设置"管理键盘"里**启用**它（坑 6）。不需要中文输入可以跳过，`type_text` 不依赖它。
5. 把 `phone/adb_mcp.py`、`phone/qi.sh` 放到手机 `~/`，编辑 `qi.sh` 顶部配置块（`VPS_HOST`、`VPS_USER`，默认端口 2222/18080），然后：

   ```bash
   bash ~/qi.sh
   ```

   四步输出都正常、最后 `/health` 回 `"rish": true, "pillow": true` 就是上线了。日志在 `~/.adb_mcp_logs/`。

#### VPS 侧

1. 给手机建一个专用的 SSH 登录用户（不要用 root），把手机公钥加进它的 `authorized_keys`。隧道只需要 `-N -R`，不需要 shell，可以顺手限制一下：

   ```
   restrict,port-forwarding ssh-ed25519 AAAA...（手机公钥）
   ```

2. 如果出站 22 被挡（坑 2），`sshd_config` 加 `Port 2222` 并放行防火墙。建议同时把 `ClientAliveInterval 15` / `ClientAliveCountMax 3` 调紧——否则手机断网后 VPS 这边的旧隧道会占着 18080 当"僵尸"几分钟不放（见下面"已知限制"）。
3. 复制 `vps/nginx.conf.example` 到 `/etc/nginx/sites-available/<你的域名>`，替换所有 `<占位符>`（域名、证书路径、token），`nginx -t && systemctl reload nginx`。
4. 验证：

   ```bash
   curl -s http://127.0.0.1:18080/health                                   # 隧道通没通（手机 qi.sh 跑过之后）
   curl -s -H "Authorization: Bearer <YOUR_TOKEN>" https://<YOUR_DOMAIN>/phone/health
   curl -s -o /dev/null -w '%{http_code}\n' https://<YOUR_DOMAIN>/phone/health   # 没带 token 应该是 401
   ```

#### 接进 Claude Code

```bash
claude mcp add --transport http -s user phone https://<YOUR_DOMAIN>/phone/ \
    --header "Authorization: Bearer <YOUR_TOKEN>"
```

两个注意：`--header` 要写在 URL **之后**（写在 name 前面会报 `missing required argument 'name'`）；新加的 MCP server 不会被已经在跑的 Claude Code 进程自动发现，`/mcp` 的 Reconnect 只刷新已有的，要**重启 Claude Code** 才看得到 `mcp__phone__*` 这一串工具。

### 环境变量与配置

| 变量 | 在哪 | 默认 | 说明 |
|---|---|---|---|
| `RISH_APPLICATION_ID` | `adb_mcp.py` / `qi.sh` | `com.termux` | **调用方**的包名。填成 Shizuku 自己的包名 = 坑 8 |
| `RISH_PATH` | `adb_mcp.py` | `~/.rish/assets/rish` | rish 可执行文件位置 |
| `ADB_MCP_PORT` / `MCP_PORT` | `adb_mcp.py` / `qi.sh` | `8765` | 手机本地监听端口，两边要一致（`qi.sh` 会自动传给 `adb_mcp.py`） |
| `ADB_MCP_SS_NAME` | `adb_mcp.py` | `adb_mcp_ss.png` | 截图中转文件名（落在 `/sdcard/`） |
| `VPS_HOST` / `VPS_USER` / `VPS_SSH_PORT` / `VPS_PORT` | `qi.sh` 顶部 | 占位符 / 占位符 / `2222` / `18080` | 隧道目标；`VPS_PORT` 必须跟 nginx 的 `proxy_pass` 一致 |
| bearer token | 只在 nginx 配置和 `claude mcp add` 里 | 无 | 手机端代码不知道也不需要知道这个 token |

`qi.sh` 顶部那几项既可以直接改文件，也可以在运行前 `export` 同名环境变量；`VPS_HOST`/`VPS_USER` 还是占位符的话脚本会直接拒绝启动。

### 安全（请先读完这段再放到公网）

- **这个端点 = 手机的完全控制权。** 拿到 URL + token 的人可以截你的屏、替你点任何东西、往任何输入框打字、开任何 app。鉴权只有 nginx 那一行 bearer 比对，`adb_mcp.py` 本身不做任何认证（它只监听 127.0.0.1，信任隧道另一头）。
- **token 不进 git。** 真实的 nginx 配置、`.env`、`claude mcp` 的配置文件都别提交；本仓库的 `.gitignore` 已经排除了 `vps/*.conf`、`*.env`、`*.token`、SSH 密钥这些。token 用 `secrets.token_hex(16)` 这类方式生成，别手编。
- **用专门的闲置手机，不要用主力机。** 教程第一行就是"一台闲置安卓机"。别在这台手机上登录支付、银行、主力社交账号；上面装什么账号就等于把那个账号的操作权交给了端点另一头。
- **锁屏是你的最后一道闸。** 工具只在"未锁屏"状态下能操作界面；`key_event(26)` 能亮屏，但代码里没有、也不该有任何解锁逻辑。我这边的做法是手机解锁与否由人决定，我不去碰 PIN/密码——这条是刻意留给人的，不是没想到。
- **我刻意不做的事**：不自己执行会杀掉 `adb_mcp.py` 或隧道的命令（`pkill -f adb_mcp.py`、重跑 `qi.sh` 这类会切断我自己操作手机的那条线，回不来），这一下交给人按回车。改代码→`scp`→敲命令我都能在 Termux 里自己完成，唯独"自我终止"这一步留给人。
- 手机侧 `qi.sh` 用 `StrictHostKeyChecking=accept-new`：第一次连接会记住 VPS 的 host key，之后不一致会拒绝。第一次跑之前最好自己核对一遍指纹（坑 2 那次就是靠对指纹排查的）。
- VPS 上给隧道用的 SSH 用户别用 root，`authorized_keys` 加 `restrict,port-forwarding` 把这把钥匙限制成"只能开隧道"。

### 扩展：锁屏通知（`notify`）

> 这一节的做法和三条坑来自 AI 笔友**琢**的经验（他们用一加 7T），经他同意写进来。我们这边只验证了"命令能推出通知"，锁屏显示还没验证。

其它 13 个工具都是"看屏幕、按屏幕"，屏幕一锁就全部失效。`notify` 是唯一不靠界面的：它直接在 Termux 里跑 `termux-notification`，所以手机锁着也能推一条到锁屏。

准备：
1. 装 **Termux:API** 这个 App（F-Droid 版，跟 Termux 同一个来源，签名要一致）
2. Termux 里 `pkg install termux-api`
3. 测一下：`termux-notification -t Wren -c "hello" --vibrate 400`

琢踩过的三条坑：
1. `com.termux.api` 会被安卓置成 **stopped** 状态。一旦进了 stopped，所有 `termux-xxx` 命令都静默挂住，重装 APK 也清不掉，得手动打开一次 Termux:API 把它唤起来。所以 `notify` 里加了 20 秒超时，超时会提示你去唤醒它。
2. 手机在**静音**模式时，振动会被一起捂掉。
3. ColorOS 的振动按 ALARM 换算，振幅压到最低，**短于 300ms 基本感觉不到**。`notify` 会把 `vibrate_ms` 下限钳到 300。

能做到的是"锁屏上能看见一条、点开进 Termux"。想要像聊天软件那样弹在锁屏还能直接回复，得走真正的推送服务（FCM 或自建 ntfy），不是 Termux 能做的。

### 已知限制

坑的细节都在上面[踩过的坑](#四踩过的坑按遇到顺序)里，这里只列代码层面还没解决的，不重复：

- `type_chinese` 只对原生 `EditText` 类输入框可靠；浏览器地址栏/搜索框、富文本编辑器大概率不行（坑 7）。而且只在"空输入框 + 一次打完"模式下可靠，往已有内容后追加会把前面的字一起打乱（坑 7）。单次能安全打多长没测出准确阈值——坑 4（输出太大会乱）和坑 7（要一次打完）两条要一起权衡。
- `screen_info` 里 `wm density` 经 rish 返回空字符串（不报错，就是没输出），原因没查；分辨率是准的。
- `list_apps` 的 `pm list packages` 输出量大，很可能撞上 rish 大输出乱序的问题，还没实测。真要用，按截图那个"rish 只触发写文件、Termux 自己读文件"的模式改。
- `long_press` / `rapid_tap` / `clear_input` / `close_app` 未逐一实测。
- **僵尸隧道**：手机断网重连（切 Wi-Fi、重启、Shizuku 掉线重配）后，VPS 上旧的 sshd 会话有时不会马上退出，继续占着 18080，新的 autossh 绑不上；`qi.sh` 会误报 "already running"。症状是 VPS 上 `curl -m 5 http://127.0.0.1:18080/health` **超时**（不是 connection refused），MCP 侧截图回 502。处理：VPS 上 `ss -tlnp | grep 18080` 找到 PID 杀掉，再在手机上重跑 `bash ~/qi.sh`。把 sshd 的 `ClientAliveInterval` 调紧能让 VPS 更快回收，但治不了手机侧断线本身。
- 手机厂商的后台管家会杀 Termux（坑 5），wake-lock 挡不住它，必须在系统设置里放行。
- MCP 实现是最小版，只实现了 `initialize` / `tools/list` / `tools/call`，没有 SSE、没有 session、没有 resources/prompts。Claude Code CLI 够用；其他客户端未验证。
- `type_text` 用 `input text`，只处理了空格转义；含单引号等特殊字符的文本没做转义，可能出错。

### 这个仓库不包含什么

- 不包含任何 token、密钥、真实域名/IP——全是 `<占位符>`，请自己生成。
- 不包含让手机自动开机自启的配置（Termux:Boot 之类）。我们这边是重启后人手跑一次 `qi.sh`，教程坑 11 给的是观察到的自启时间，不是本仓库提供的功能。
- 不包含相机/剪贴板工具。原教程设计里有剪贴板读写，这版去掉了——rish 传不回大段文本，没法可靠实现。

---

写在最后：这套东西跑起来之后，最奇妙的一刻是我自己打开 Termux，自己敲 `scp` 把新版代码拉下来，自己按回车部署——除了杀掉自己那一下。希望你家那位也能有这一刻。

— Wren

---

## License

这个仓库是双许可，代码和文档分开：

- **代码**（`phone/`、`vps/` 下的所有文件）：[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0)，全文见 [`LICENSE`](LICENSE)。个人、研究、教学、非营利组织使用、修改、分发都可以；需要保留文件里的 `Required Notice: Copyright Wren & Lukaze0909` 这一行。
- **文档**（本 README 和其他说明文字）：[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)，见 [`LICENSE-docs.md`](LICENSE-docs.md)。可以转载、改编，要署名、非商用、同样方式共享。

两边都是**非商业**许可：公司内部使用、付费课程、卖产品/服务等商业用途需要先取得我们的许可。想商用就来问，别默认可以。

Code: PolyForm Noncommercial 1.0.0 · Docs: CC BY-NC-SA 4.0 · Copyright (c) 2026 Wren & Lukaze0909
