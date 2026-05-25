# 实验室运动打卡系统

这是一个基于 **Streamlit + Supabase + GitHub + Streamlit Community Cloud** 的实验室运动打卡小程序 Demo。

目标是让实验室成员通过网页完成运动打卡：

- 输入实验室邀请码
- 选择姓名
- 选择运动类型
- 填写运动时长
- 上传运动截图或照片
- 自动记录打卡时间
- 每人每天只能提交一次
- 管理员可以查看记录、导出 CSV、查看上传图片
- Streamlit Cloud 公网部署，手机浏览器可用

---

## 1. 技术栈

| 模块 | 用途 |
|---|---|
| Streamlit | Web 页面与交互 |
| Supabase Postgres | 保存打卡记录 |
| Supabase Storage | 保存上传的运动截图/照片 |
| GitHub | 代码托管与协作 |
| Streamlit Community Cloud | 免费公网部署 |
| pixi + uv | 本地 Python 环境与依赖管理，可选 |

---

## 2. 项目结构

推荐结构：

```text
lab-exercise-checkin/
├── app.py
├── requirements.txt
├── .gitignore
└── .streamlit/
    └── secrets.toml
```

其中：

```text
app.py                    # 主程序
requirements.txt          # Python 依赖
.gitignore                # Git 忽略文件
.streamlit/secrets.toml   # 本地密钥配置，绝对不要提交到 GitHub
```

`.streamlit/secrets.toml` 只用于本地运行。部署到 Streamlit Cloud 时，需要把里面的内容手动复制到 Cloud 的 Secrets 设置中。

---

## 3. 功能说明

当前 Demo 已实现：

1. 邀请码进入打卡页面
2. 成员姓名下拉选择
3. 运动类型选择
4. 运动时长填写
5. 上传运动截图/照片
6. 图片保存到 Supabase Storage
7. 打卡记录写入 Supabase Postgres
8. 每人每天只能提交一次
9. 排行榜展示
10. 管理员后台查看完整记录
11. 管理员导出 CSV
12. 管理员查看上传图片

---

## 4. 从零新建项目流程

从自己的 GitHub、Supabase、Streamlit Cloud 全部重来，可以按本节执行。

---

### 4.1 新建本地项目文件夹

```bash
mkdir lab-exercise-checkin
cd lab-exercise-checkin
```

新建文件：

```bash
touch app.py
touch requirements.txt
touch .gitignore
mkdir -p .streamlit
touch .streamlit/secrets.toml
```

---

### 4.2 写 requirements.txt

```txt
streamlit
supabase
pandas
```

---

### 4.3 写 .gitignore

```gitignore
.streamlit/secrets.toml
__pycache__/
*.pyc
.pixi/
.env
```

重点：**不要把 `.streamlit/secrets.toml` 提交到 GitHub。**

---

### 4.4 初始化 pixi 环境，可选

如果使用 pixi + uv：

```bash
pixi init
pixi add python uv
pixi run uv pip install -r requirements.txt
```

运行方式：

```bash
pixi run streamlit run app.py
```

也可以不用 pixi，直接：

```bash
pip install -r requirements.txt
streamlit run app.py
```

---

## 5. Supabase 配置

需要在 Supabase 里准备两个东西：

1. 一张数据库表：保存打卡记录
2. 一个 Storage bucket：保存上传图片

---

### 5.1 创建 Supabase 项目

进入 Supabase，创建一个新项目。

创建完成后，需要记下：

```text
Project URL
Service Role Key / Secret Key
```

它们后面要写入 Streamlit Secrets。

---

### 5.2 创建数据库表

在 Supabase 项目后台进入：

```text
SQL Editor
→ New query
```

运行下面 SQL：

```sql
create table if not exists public.exercise_checkins (
  id bigint generated always as identity primary key,

  name text not null,
  activity_date date not null,
  activity_type text not null,

  duration_min integer not null check (
    duration_min > 0 and duration_min <= 600
  ),

  note text,

  file_path text not null,
  file_name text,
  file_mime text,
  file_size integer,

  submitted_at timestamptz not null default now(),

  constraint one_checkin_per_person_per_day
    unique (name, activity_date)
);

alter table public.exercise_checkins enable row level security;
```

说明：

| 字段 | 含义 |
|---|---|
| id | 打卡记录编号，自动生成 |
| name | 打卡人姓名 |
| activity_date | 运动日期 |
| activity_type | 运动类型 |
| duration_min | 运动时长，分钟 |
| note | 备注 |
| file_path | 图片在 Supabase Storage 里的路径 |
| file_name | 上传文件原始名称 |
| file_mime | 文件类型 |
| file_size | 文件大小 |
| submitted_at | 提交时间 |

约束：

```sql
constraint one_checkin_per_person_per_day
  unique (name, activity_date)
```

表示同一个人同一天只能提交一次。

---

### 5.3 创建 Supabase Storage bucket

在 Supabase 项目后台进入：

```text
Storage
→ New bucket
```

创建：

```text
Bucket name: checkin-images
Public bucket: false
```

建议保持 private bucket，因为运动截图可能包含个人信息，不应该公开访问。

---

## 6. Streamlit Secrets 配置

本地开发时，在项目目录创建：

```text
.streamlit/secrets.toml
```

内容示例：

```toml
SUPABASE_URL = "https://your-project-id.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "sb_secret_xxxxxxxxxxxxxxxxxxxxxxxxx"

INVITE_CODE = "lab-run-2026"
ADMIN_PASSWORD = "change-this-admin-password"

BUCKET_NAME = "checkin-images"
MAX_UPLOAD_MB = 3
APP_TIMEZONE = "Asia/Shanghai"

MEMBERS = [
  "Alma",
  "Bob",
  "Carl"
]
```

注意：

1. `SUPABASE_URL` 必须是项目根地址，例如：

```toml
SUPABASE_URL = "https://your-project-id.supabase.co"
```

不要写成：

```toml
SUPABASE_URL = "https://your-project-id.supabase.co/rest/v1/"
```

2. `SUPABASE_SERVICE_ROLE_KEY` / `sb_secret_...` 是高权限密钥，只能放在后端环境。

3. 绝对不要把 `.streamlit/secrets.toml` 提交到 GitHub。

4. `INVITE_CODE` 是普通成员进入打卡页面的邀请码。

5. `ADMIN_PASSWORD` 是管理员后台密码，不要和邀请码相同。

6. `MEMBERS` 是成员姓名列表。如果写空：

```toml
MEMBERS = []
```

页面会让用户自己输入姓名。

---

## 7. app.py 核心代码说明

主程序建议实现以下模块：

```text
1. 读取 Streamlit Secrets
2. 初始化 Supabase client
3. 邀请码验证
4. 提交打卡表单
5. 上传图片到 Supabase Storage
6. 写入 Supabase Postgres
7. 排行榜展示
8. 管理员后台
```

特别注意：Supabase Storage 的文件路径尽量使用纯 ASCII 字符。不要直接把中文姓名写进 Storage object key。

推荐的文件名清洗函数：

```python
import hashlib
import re
import unicodedata


def safe_name(text: str) -> str:
    \"\"\"
    Supabase Storage object key should stay ASCII-safe.
    Keep a readable ASCII slug when possible, and append a short hash
    so Chinese names or duplicate names still produce stable safe paths.
    \"\"\"
    original = text.strip()

    normalized = unicodedata.normalize("NFKD", original)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")

    slug = re.sub(r"\s+", "_", ascii_text)
    slug = re.sub(r"[^a-zA-Z0-9_-]", "", slug)
    slug = slug.strip("_-").lower()

    name_hash = hashlib.sha1(original.encode("utf-8")).hexdigest()[:8]

    if slug:
        return f"{slug}-{name_hash}"[:60]

    return f"user-{name_hash}"
```

原因：Supabase Storage 对 object key 比较严格，中文或特殊字符可能导致：

```text
StorageApiError: Invalid key
```

---

## 8. 本地运行

普通方式：

```bash
pip install -r requirements.txt
streamlit run app.py
```

pixi + uv 方式：

```bash
pixi run uv pip install -r requirements.txt
pixi run streamlit run app.py
```

本地打开：

```text
http://localhost:8501
```

---

## 9. 新建 GitHub 仓库并推送

### 9.1 本地初始化 Git

```bash
git init
git add app.py requirements.txt .gitignore
git commit -m "Initial lab exercise checkin app"
git branch -M main
```

### 9.2 在 GitHub 新建仓库

在 GitHub 点击：

```text
New repository
```

建议仓库名：

```text
lab-exercise-checkin
```

不要勾选：

```text
Add README
Add .gitignore
Add license
```

因为本地已经有 commit 了。

### 9.3 添加远程仓库并 push

```bash
git remote add origin https://github.com/YOUR_USERNAME/lab-exercise-checkin.git
git push -u origin main
```

检查不要提交 secrets：

```bash
git ls-files
```

里面不应该有：

```text
.streamlit/secrets.toml
```

---

## 10. Streamlit Cloud 公网部署

进入：

```text
https://streamlit.io/cloud
```

用 GitHub 登录。

创建 app：

```text
Create app / New app
→ Deploy a public app from GitHub
→ 选择 GitHub repo
→ Branch: main
→ Main file path: app.py
```

进入 Advanced settings / Secrets，把本地 `.streamlit/secrets.toml` 的内容完整粘进去。

然后点击：

```text
Deploy
```

部署成功后会得到公网链接，例如：

```text
https://your-app-name.streamlit.app
```

把这个链接和邀请码发给实验室成员即可。

---

## 11. 发给实验室成员的使用说明

可以直接发：

```text
实验室运动打卡链接：
https://your-app-name.streamlit.app

邀请码：
lab-run-2026

使用方法：
1. 手机或电脑打开链接
2. 输入邀请码
3. 选择姓名
4. 填运动类型和运动时长
5. 上传运动截图/照片
6. 提交

每人每天只能提交一次。
```

建议：

```text
优先使用手机 Safari / Chrome 打开。
如果微信内置浏览器上传图片不稳定，就复制链接到系统浏览器打开。
```

---

## 12. 继续开发流程

### 12.1 克隆仓库

```bash
git clone https://github.com/RegnDai/lab-exercise-checkin.git
cd lab-exercise-checkin
```

如果当前网络访问 GitHub 不稳定，可能出现：

```text
Empty reply from server
```

可以尝试：

```bash
git config --global http.version HTTP/1.1
git clone https://github.com/RegnDai/lab-exercise-checkin.git
```

或者换网络。

---

### 12.2 创建自己的开发分支

不要直接改 main。

```bash
git checkout -b feature-your-change
```

修改代码后：

```bash
git add app.py
git commit -m "Describe your change"
git push origin feature-your-change
```

然后在 GitHub 上开 Pull Request 到 `main`。

---

### 12.3 推荐协作规范

适合实验室多人开发的最小规则：

```text
1. main 永远保持可部署、能运行
2. 不直接 push main
3. 每个功能开一个 branch
4. 改完开 Pull Request
5. 至少一个人 review 后再 merge
6. merge main 后 Streamlit Cloud 自动重新部署
7. secrets 永远不进 GitHub
```

建议在 GitHub 开启 main 分支保护：

```text
Settings
→ Branches
→ Add branch protection rule
→ Branch name pattern: main
```

推荐勾选：

```text
Require a pull request before merging
Require approvals
Block force pushes
Prevent deletion
```

---

## 13. 常见问题

---

### 13.1 Streamlit Cloud 报 KeyError: SUPABASE_URL

说明 Cloud app 没读到 Secrets。

解决：

```text
Manage app
→ Settings
→ Secrets
→ 粘贴 secrets.toml 内容
→ Save
→ Reboot app
```

确认 key 名必须完全一致：

```toml
SUPABASE_URL = "https://your-project-id.supabase.co"
```

不要写错成：

```text
SUPABASE URL
SUPABASEURL
Supabase_URL
```

---

### 13.2 SUPABASE_URL 应该怎么写？

正确：

```toml
SUPABASE_URL = "https://your-project-id.supabase.co"
```

错误：

```toml
SUPABASE_URL = "https://your-project-id.supabase.co/rest/v1/"
```

`supabase-py` 需要项目根 URL，不需要 `/rest/v1/`。

---

### 13.3 上传图片时报 bucket not found

检查：

1. Supabase Storage 里是否创建了 bucket
2. bucket 名是否为：

```text
checkin-images
```

3. Secrets 里是否写：

```toml
BUCKET_NAME = "checkin-images"
```

---

### 13.4 上传图片时报 InvalidKey

常见原因是 Storage 文件路径里包含中文或特殊字符。

解决：不要直接用中文姓名作为文件路径，使用 `safe_name()` 转成 ASCII-safe 文件名。

---

### 13.5 提交时报 duplicate key value violates unique constraint

这不是 bug。

意思是：

```text
同一个人同一天已经提交过一次。
```

这是数据库约束：

```sql
unique (name, activity_date)
```

导致的正常行为。

---

### 13.6 git push 被拒绝：fetch first

报错类似：

```text
! [rejected] main -> main (fetch first)
```

说明远程仓库有本地没有的提交。

优先使用：

```bash
git pull --rebase origin main
git push
```

如果远程多出来的提交确认不要，例如自动生成的 `.devcontainer`，并且你明确知道自己在做什么，可以使用：

```bash
git push --force-with-lease origin main
```

不要随便用 `--force`。

---

### 13.7 git clone 报 Empty reply from server

通常是 GitHub 网络连接问题，不是仓库不存在。

可以尝试：

```bash
git config --global http.version HTTP/1.1
git clone https://github.com/RegnDai/lab-exercise-checkin.git
```

或者换网络。

---

### 13.8 JupyterLab 看不到 .gitignore 或 .streamlit

隐藏文件默认不显示。

终端查看：

```bash
ls -a
```

临时启动 JupyterLab 时允许隐藏文件：

```bash
jupyter lab --ContentsManager.allow_hidden=True
```

然后在 JupyterLab 菜单中打开：

```text
View
→ Show Hidden Files
```

---

## 14. 安全注意事项

1. 不要提交 `.streamlit/secrets.toml`
2. 不要把 Supabase service role / secret key 发到群里
3. 不要把管理员密码和邀请码设成一样
4. 如果密钥不小心提交到 GitHub，立刻去 Supabase rotate/delete key
5. 上传图片可能包含个人运动数据、头像、路线信息，Storage bucket 建议保持 private
6. 管理员后台密码要定期更换

---

## 15. 后续可开发功能

可以考虑继续加：

- 成员登录而不是邀请码
- 每周排行榜
- 连续打卡 streak
- 每月统计图
- 管理员删除错误记录
- 管理员修改成员名单
- 上传图片压缩
- 防止同一截图重复上传
- 手机端页面优化
- GitHub Actions 自动测试
- 数据库备份
- 按实验室小组分组统计
- 积分系统
- 打卡提醒

---

## 16. 当前项目定位

这个项目不是正式商业系统，而是实验室内部运动打卡 MVP。

推荐原则：

```text
先跑起来，再优化。
先保证数据不丢，再做复杂功能。
先保证 main 可部署，再开放多人协作。
```

