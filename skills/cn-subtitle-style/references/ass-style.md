# ASS 样式档案

这些默认值来自用户两份人工成品：“无标题.ass”和“analog-horror.en.ass”。有用户指定的参考 ASS 时，直接继承参考文件，不用默认值覆盖。

## 通用规则

- PlayResX / PlayResY 必须等于源视频尺寸。
- 下表数值以 1920×1080 为基准；其他尺寸按 PlayResY / 1080 等比缩放字号和边距。
- 字体使用微软雅黑。ASS 中的“微软雅黑”与“Microsoft YaHei”是同一字体；扩展已有文件时保持原写法。
- PrimaryColour 为白色，OutlineColour 为黑色，底部居中。
- 新文件使用清晰的样式名；扩展已有文件时保留其原样式名，包括历史拼写。

## 英文单语初稿

对应现有英文 V2 稿及 720p 短视频：

| 字段 | 1080p |
|---|---:|
| Fontname | Microsoft YaHei |
| Fontsize | 46 |
| Bold | 0 |
| Outline | 2.2 |
| Shadow | 0.8 |
| Alignment | 2 |
| MarginL / MarginR | 60 / 60 |
| MarginV | 46 |
| WrapStyle | 2 |

720p 等比例结果为字号 31、左右边距 40、垂直边距 31。

## 中文单语

来自“无标题.ass”的主样式，共 283 条正文使用：

| 字段 | 1080p |
|---|---:|
| Fontname | 微软雅黑 |
| Fontsize | 70 |
| Bold | -1 |
| Outline | 2 |
| Shadow | 2 |
| Alignment | 2 |
| MarginL / MarginR | 10 / 10 |
| MarginV | 50 |
| WrapStyle | 0 |

正文以单行为主。不要把文件中未使用的 Arial 20 Default 样式误认成用户偏好。

## 中英双语

来自用户人工加工的 330 条双语成品：

| 字段 | 1080p |
|---|---:|
| Fontname | 微软雅黑 |
| Fontsize | 60 |
| Bold | -1 |
| Outline | 2 |
| Shadow | 2 |
| Alignment | 2 |
| MarginL / MarginR | 10 / 10 |
| MarginV | 20 |
| WrapStyle | 2 |

文本顺序固定为 中文\NEnglish。若英文因屏幕宽度拆成多条而中文仍是一个自然语义单元，允许连续几条重复同一中文；这是用户人工成品中的明确做法，不算重复翻译缺陷。

## 译者注释和画面文字

- 左上译注：微软雅黑 70、粗体、Alignment 7；以 * 开头。
- 左下补充：微软雅黑 70、粗体、Alignment 1。
- 蓝色译注使用 {\c&H7F7FFF&}；与被解释的正文同时出现时，位置必须不同，建议单独样式并放在更高 Layer。
- 不确定译法可给具体短语加 {\u1}...{\u0}，并在短语后写（？）。
- 强调画面文字可使用 \fs90 / \fs70 和颜色标签；强调结束后必须恢复字号与颜色。

## 样式检查

- 参考 ASS 中的人工样式优先级高于本表。
- 不把测试稿的样式当成用户偏好。
- 压制前抽查中文、英文、双语和译注各至少一处，确认字体存在、位置不遮挡画面、行宽未溢出。
