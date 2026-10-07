# 数据流设计

## 热搜采集流

```text
调度器
  ↓
热搜采集器
  ↓
HTTP 响应
  ↓
平台解析器
  ↓
RawItem(hotsearch)
  ↓
原始数据存储
```

当热搜词需要具体帖子或视频证据时，进入扩展检索：

```text
热搜词
  ↓
MediaCrawler 关键词任务
  ↓
Top N 帖子 / 视频
  ↓
评论证据
  ↓
情感分析
```

## 关键词检索流

```text
配置的关键词层级
  ↓
任务构建器
  ↓
MediaCrawler 执行器
  ↓
JSONL 结果
  ↓
平台映射器
  ↓
RawItem(keyword_search)
```

## 指定账号检索流

```text
配置的已授权账号
  ↓
任务构建器
  ↓
MediaCrawler creator 任务
  ↓
JSONL 结果
  ↓
平台映射器
  ↓
RawItem(account)
```

## 清洗流

```text
RawItem
  ↓
字段规范化
  ↓
发布时间解析
  ↓
时效过滤
  ↓
URL 规范化
  ↓
精确 / 近似 URL 去重
  ↓
标题与内容相似度去重
  ↓
初步属性分类
  ↓
CleanItem
```

## 研判流

```text
CleanItem
  ├── 关键词属性规则
  ├── 来源权重
  ├── 热搜排名与热度规范化
  ├── LLM 分类与置信度
  ├── 地域实体
  ├── 评论证据与情感
  └── LLM 风险建议
          ↓
加权综合评分
  ↓
预警级别
  ↓
StructuredOutputEvent
```

## 产出流

```text
StructuredOutputEvent
  ↓
钉钉 Payload 格式化器
  ↓
投递策略
  ↓
Webhook 客户端
  ↓
投递台账
```

## 状态流

每个阶段应显式记录：

```text
pending
running
succeeded
failed
skipped
manual_review
```

任务重启时依赖稳定 ID与状态表恢复，不依赖进程内存。
