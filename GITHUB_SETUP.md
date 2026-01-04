# GitHub 仓库设置指南

## 步骤 1: 在 GitHub 上创建仓库

1. 访问 https://github.com/new
2. 填写仓库信息：
   - **Repository name**: `TourRAG`
   - **Description**: `景点多模态 RAG 系统 - 全本地、Tag 驱动`
   - **Visibility**: Public 或 Private（根据你的选择）
   - **不要** 初始化 README、.gitignore 或 license（我们已经有了）
3. 点击 "Create repository"

## 步骤 2: 推送代码

创建仓库后，运行以下命令：

```bash
cd /Users/z3548881/Desktop/TourRAG/TourRAG_code
git push -u origin main
```

如果提示需要认证，请使用以下方式之一：

### 方式 A: 使用 Personal Access Token (推荐)

1. 访问 https://github.com/settings/tokens
2. 点击 "Generate new token (classic)"
3. 选择权限：至少需要 `repo` 权限
4. 生成 token 后，在推送时使用：
   ```bash
   git push -u origin main
   # Username: wgh1992
   # Password: <你的 personal access token>
   ```

### 方式 B: 使用 SSH

1. 生成 SSH key（如果还没有）：
   ```bash
   ssh-keygen -t ed25519 -C "your_email@example.com"
   ```

2. 添加 SSH key 到 GitHub：
   - 复制公钥：`cat ~/.ssh/id_ed25519.pub`
   - 访问 https://github.com/settings/keys
   - 点击 "New SSH key"，粘贴公钥

3. 更改远程 URL：
   ```bash
   git remote set-url origin git@github.com:wgh1992/TourRAG.git
   git push -u origin main
   ```

## 步骤 3: 验证

推送成功后，访问：
https://github.com/wgh1992/TourRAG

你应该能看到所有文件已经上传。

## 当前 Git 状态

- ✅ Git 仓库已初始化
- ✅ 所有文件已添加
- ✅ 已创建 2 个提交
- ✅ 远程仓库已配置
- ⏳ 等待推送到 GitHub

## 提交历史

```
875a8df Add GitHub CI workflow and update documentation
ca397fd Initial commit: TourRAG - 景点多模态 RAG 系统
```

## 包含的文件

- 完整的应用代码（app/）
- 数据库迁移脚本（migrations/）
- 数据插入脚本（scripts/）
- 配置文件（config/）
- 测试文件（tests/）
- 文档（README.md, ARCHITECTURE.md, USAGE.md 等）
- GitHub Actions CI 工作流

## 注意事项

- `.env` 文件已被 `.gitignore` 排除，不会上传
- 敏感信息（API keys）不会提交到仓库
- 数据库文件不会上传

