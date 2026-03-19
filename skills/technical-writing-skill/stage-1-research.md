# 阶段 1: 深度调研 🔍

## 目标

通过**大量的搜索、抓取、阅读、分析**，形成对主题的深入理解，为后续创作提供坚实的知识基础。

**⚠️ 核心要求**: 这是整个写作流程中**最重要的阶段**，必须投入足够的时间和精力进行全面调研。

---

## 执行步骤

### 1. 制定调研计划

根据 `00-topic.md` 中确定的主题，列出需要调研的内容：

#### 必须调研的内容

- **官方文档**: 技术的官方文档、API 参考、Changelog
- **开源项目**: GitHub 上的官方 repo、示例项目、相关实现
- **社区博客**: 技术博客、Medium 文章、开发者分享
- **视频教程**: YouTube、B站的相关教程（如有）
- **社区讨论**: GitHub Issues、Stack Overflow、Reddit、Discord

#### 调研清单（示例）

假设主题是 "LangGraph 1.0 实战教程"：

```markdown
**调研清单**:

1. **官方资源**:
   - [ ] LangGraph 1.0 官方文档（重点：核心概念、新特性）
   - [ ] LangGraph GitHub repo（重点：examples/、CHANGELOG.md）
   - [ ] LangSmith 相关文档（如涉及调试和监控）

2. **开源项目**:
   - [ ] 搜索 GitHub: "langgraph 1.0 example"
   - [ ] 搜索 GitHub: "langgraph agent tutorial"
   - [ ] 查看 LangChain 官方的 cookbooks

3. **社区内容**:
   - [ ] 搜索 Medium/Dev.to: "langgraph 1.0"
   - [ ] 搜索 YouTube: "langgraph tutorial 2026"
   - [ ] 查看 LangChain Discord 中的讨论

4. **竞品分析**:
   - [ ] 其他人写的 LangGraph 教程（了解哪些内容已经被覆盖）
   - [ ] 找出差异点和可以深挖的角度
```

---

### 2. 执行调研（使用工具）

#### 工具 1: WebSearch（网络搜索）

**使用场景**: 快速找到相关资源、博客、讨论

```typescript
// 示例调用
WebSearch: "LangGraph 1.0 new features 2026"
WebSearch: "LangGraph tutorial GitHub"
WebSearch: "LangGraph vs AutoGen comparison"
```

**搜索策略**:
- 使用英文关键词（技术文档大多是英文）
- 加上年份（如 "2026"）确保是最新内容
- 使用 `site:` 限定网站（如 `site:github.com langgraph example`）

#### 工具 2: WebFetch（抓取网页内容）

**使用场景**: 深度阅读某个文档、博客、GitHub README

```typescript
// 示例调用
WebFetch: "https://langchain-ai.github.io/langgraph/concepts/high_level/"
WebFetch: "https://github.com/langchain-ai/langgraph/blob/main/examples/multi_agent/agent_supervisor.ipynb"
```

**抓取重点**:
- 官方文档的核心概念章节（至少 3 章）
- 开源项目的 README 和关键代码文件
- 高质量博客的技术细节部分

#### 工具 3: Context7 MCP（获取库文档）

**使用场景**: 获取特定库的最新 API 文档和代码示例

```typescript
// 示例调用（通过 MCP）
resolve-library-id: "langgraph"
query-docs: libraryId="/langchain-ai/langgraph", query="how to create multi-agent system"
```

**优势**: 获取最新、结构化的 API 文档

#### 工具 4: Bash（克隆和运行示例项目）

**使用场景**: 克隆官方示例项目，本地运行验证

```bash
# 示例操作
cd /Users/henry/Desktop/apex/user/workspace/projects
git clone https://github.com/langchain-ai/langgraph.git
cd langgraph/examples
# 浏览示例代码
```

**⚠️ 注意**: 只在必要时克隆，避免占用过多磁盘空间

---

### 3. 记录调研结果

在调研过程中，持续记录以下内容：

#### Key Findings（关键发现）

**必须包含**:
- **核心概念**: 这个技术的核心思想是什么？
- **新特性**: 与旧版本或竞品相比，有哪些新功能？
- **最佳实践**: 官方推荐的使用方式是什么？
- **常见坑**: 社区讨论中提到的常见问题和解决方案
- **实际案例**: 有哪些真实项目在使用？效果如何？

#### 信息来源（Source Links）

**每个关键发现都要标注来源**:

```markdown
**核心概念**: LangGraph 1.0 引入了 StateGraph 作为核心抽象
- 来源: https://langchain-ai.github.io/langgraph/concepts/high_level/
- 相关代码: https://github.com/langchain-ai/langgraph/blob/main/examples/state_graph.py
```

#### 代码示例收集

**收集至少 3-5 个可运行的代码示例**:
- 来自官方文档
- 来自开源项目
- 来自社区博客

**记录每个示例的**:
- 功能说明
- 代码来源
- 是否可直接运行（如需修改，记录需要修改的部分）

---

### 4. 填充调研报告模板

读取模板：

```
Read: {SKILL_LOCATION}/skills/technical-writing-skill/templates/01-research-template.md
```

根据调研结果填充模板。

---

### 5. 质量检查

在完成调研后，参考检查清单：

```
Read: {SKILL_LOCATION}/skills/technical-writing-skill/checklists/research-checklist.md
```

**自查要点**:
- [ ] 是否阅读了至少 3 章官方文档？
- [ ] 是否分析了至少 2 个开源项目？
- [ ] 是否阅读了至少 3 篇社区博客？
- [ ] 是否收集了至少 1 个可运行的示例？
- [ ] 每个关键发现是否都有来源链接？

---

### 6. 保存调研报告

```
Write: wikis/writing/drafts/{article-slug}/01-research.md
```

---

### 7. 向用户展示 Key Findings

**输出格式**:

```markdown
✅ 深度调研完成！

**调研范围**:
- 官方文档: {数量} 章节
- 开源项目: {数量} 个
- 社区博客: {数量} 篇
- 代码示例: {数量} 个

**关键发现（Key Findings）**:

1. **{发现 1 标题}**
   - {简要说明}
   - 来源: {链接}

2. **{发现 2 标题}**
   - {简要说明}
   - 来源: {链接}

3. **{发现 3 标题}**
   - {简要说明}
   - 来源: {链接}

...（列出 5-8 个关键发现）

**完整调研报告**: 已保存至 `wikis/writing/drafts/{article-slug}/01-research.md`

**请查看调研报告，确认以下内容**:
- 调研范围是否充分？
- 关键发现是否准确？
- 是否需要补充某些方面的调研？

**确认无误后，我将进入阶段 2：大纲设计。**
```

---

## 常见问题

### Q: 调研到什么程度才算"充分"？

A: 参考以下标准：

- **广度**: 覆盖官方文档、开源项目、社区内容
- **深度**: 至少深入阅读 3-5 个核心资源（不是只看标题）
- **时效性**: 确保是最新的内容（2025-2026 年）
- **可执行性**: 至少有 1 个可运行的代码示例

### Q: 如果找不到足够的资源怎么办？

A: 两种情况：

1. **技术太新**: 如果是刚发布的技术，可能资源较少
   - 重点依赖官方文档和 GitHub repo
   - 可以直接运行官方示例，记录实践过程

2. **搜索方式有问题**: 调整搜索关键词
   - 尝试英文 + 中文关键词
   - 尝试不同的搜索引擎（Google, Bing, GitHub）

### Q: 用户说"调研不够充分"怎么办？

A: 询问用户具体需求：

```markdown
收到！我会补充调研。请问你希望我重点关注哪些方面？

- [ ] 更多代码示例？
- [ ] 更深入的源码分析？
- [ ] 更多实际应用案例？
- [ ] 与竞品的对比分析？
- [ ] 其他: __________
```

然后根据用户反馈继续调研，更新 `01-research.md`。

---

## 调研工具总结

| 工具 | 用途 | 示例 |
|------|------|------|
| **WebSearch** | 快速找资源 | `WebSearch: "LangGraph 1.0 tutorial"` |
| **WebFetch** | 深度阅读网页 | `WebFetch: "https://docs.langchain.com/..."` |
| **Context7 MCP** | 获取库文档 | `query-docs: libraryId="/langchain-ai/langgraph"` |
| **Bash (git clone)** | 克隆示例项目 | `git clone https://github.com/...` |
| **Read** | 阅读本地文件 | `Read: downloaded-example.py` |

---

## 下一步

用户确认调研充分后 → **进入阶段 2**

**需要加载的文档**:
```
Read: {SKILL_LOCATION}/skills/technical-writing-skill/stage-2-outline.md
Read: wikis/writing/technical-writing-guide.md
```
