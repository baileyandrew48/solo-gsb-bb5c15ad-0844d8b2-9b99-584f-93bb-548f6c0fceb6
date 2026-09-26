# 离线小册子拼版 API（Python / FastAPI）

按**帖（signature）**对小册子进行拼版：输入总页数、每帖最多纸张数和装订方向（左/右），
按纸张**从外到内**返回每帖各张纸正反面的左右页码。空白页用 `null` 表示。

另提供**章节分帖**接口 `/api/v1/impose/chapters`：按章节首页页码分帖，章节不可跨帖、
相邻章节可合帖，并自动选择空白最少、帖数最少的分帖边界。

还提供**重印复用**接口 `/api/v1/impose/reprint`：输入旧版与新版按阅读顺序排列的页面 ID，
在新版四页位与旧版某印张完全相同且均未改动时整张复用（允许跨帖、每张旧印张最多复用一次），
否则标记整张重印。

还提供**印张抽检**接口 `/api/v1/impose/inspect`：把车间乱序拍回的实物印张（每张可能被
原样、左右镜像、正反互换或两者组合地读出）与按相同拼版规则生成的预期印张配对，先最大化配对数、
再最大化已读页位吻合数，并逐张给出帖号/张号、解释变换与已知页位错误明细。

还提供**机台版面**接口 `/api/v1/impose/press-layout`：在上述拼版页序之上给出每张纸的纸面尺寸，
以及正反面每个页位的页码、左上角坐标与旋转角度（支持双面打印的长边 / 短边翻转），空白页位保留 `null`。

还提供**瑕疵定位**接口 `/api/v1/impose/locate-defects`：沿用机台版面的全部参数，另收瑕疵点列表
（帖号、张号、正反面、纸面左上角起算的 x/y 毫米坐标），逐点反查对应的原稿页码与阅读方向的页内坐标；
落在中缝或空白页位的点明确标记为 `gutter` / `blank` 且不返回页码。

还提供**墨区着墨面积**接口 `/api/v1/impose/ink-zones`：沿用机台版面的全部参数，另给等宽墨区数量
（1～16）、正整数印数与各页互不重叠的页内矩形及 CMYK 各通道覆盖率（0～1）；矩形按所在页位的
0°/180° 方向映射到纸面，跨墨区按交叠面积拆分，按帖、张、正反面和墨区返回各通道**等效着墨面积乘印数**
后的结果（mm²），空白页不计。

还提供**外裁/折缝安全检查**接口 `/api/v1/impose/trim-safety`：沿用机台版面的全部参数，另给非负的
外裁安全距离与折缝安全距离，并按**实际页码**给出**阅读方向**的受保护内容矩形列表；矩形越出页内返回
422。逐张逐面按页位的 0°/180° 旋转把矩形映射到纸面，中缝侧按折缝距离、其余三边（顶/底/纸面外侧）
按外裁距离检查，**贴安全线视为合格**；逐处返回帖号、张号、正反面、页码、违规边（`top`/`bottom`/
`outer`/`fold`）与纸面矩形，空白页跳过。

还提供**双面拼版校样**接口 `/api/v1/impose/proof.pdf`：参数与机台版面完全一致，直接返回可下载的
`proof.pdf`——每张印张依次生成正面、背面两页，纸面尺寸与机台版面一致，各页位标注页码、帖号与张号，
空白位标注“空白”，并画出中缝分隔线；长边 / 短边翻转的背面分别按槽位交换、旋转 180° 呈现。

还提供**订针计划**接口 `/api/v1/impose/staple-plan`：沿用 `/api/v1/impose` 的帖数与每帖张数，
接收页高（50～1000 mm）、每帖订针数（2～4 根）、上/下留边、最小针距以及按帖号给出的禁针闭区间，
在页高内的整数毫米刻度上为每帖规划递增针位，使相对理想针位的最大绝对偏差最小
（并列时先比偏差总和、再比针位序列字典序），逐帖返回针位与最大偏差；某帖无可行排列时返回指出帖号的 422。

还提供**原纸备料**接口 `/api/v1/impose/stock-plan`：沿用拼版参数算出每册印张数（含末帖补白张），
乘印数得到成品印张总需求，并沿用机台版面的成品印张尺寸（宽 `2 × 页宽 + 中缝`、高 = 页高，书脊沿页高）。
输入 1～6 种原纸的整数毫米宽高、各 0～30 张库存与沿宽/沿高的纸纹方向，以及统一的四周留边和裁切间隔；
成品只能按**书脊与纸纹平行**的唯一朝向，在扣除留边的可用区域内按**十进制尺寸**精确核算整行整列排布
（`n` 个成品加 `n−1` 个间隔不超过可用长度才计入 `n`，恰好贴边仍可排入），据此算出各规格单张出数，
并在库存内选择满足需求且**原纸总面积最小**的组合（面积并列时依次比超产最少、按输入顺序的用量字典序最小），
返回各规格用量、单张出数、总产量与余量；库存满负荷仍无法满足需求时返回明确的 422。

还提供**骑马订爬移补偿**接口 `/api/v1/impose/creep-plan`：沿用机台版面的全部参数，另收单张纸厚度
`thickness_mm`（正有限数），按帖独立计算爬移——最外张位移为 0，向内第 `n` 张爬移量为
`2 × (n−1) × thickness_mm`，该张正反面左右页位的图像均向纸面折缝中心平移该量；逐页位返回页码、
纸面水平位移与按页位 0°/180° 旋转换算的阅读方向稿件水平位移，空白页位保留且位移为 0；
任一张爬移量达到单页宽度时返回 422。

## 一条命令启动

需要安装 Docker（含 Compose 插件），在项目根目录执行：

```bash
docker compose up --build
```

该命令会自动完成：构建镜像 → 安装全部依赖 → 前台启动 API（容器内 uvicorn 直接拉起，
无数据库等额外初始化步骤）。服务默认监听 **http://localhost:8000**，按 `Ctrl+C` 停止。

希望在后台运行时改用：

```bash
docker compose up -d --build
```

停止 / 查看日志：

```bash
docker compose down        # 停止
docker compose logs -f     # 查看日志
```

## 必要配置

默认无需任何配置。唯一可选配置是**宿主机端口**（容器内固定 8000）：

```bash
HOST_PORT=9000 docker compose up -d --build
```

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `HOST_PORT` | `8000` | 宿主机暴露端口，通过环境变量覆盖；容器内端口固定为 `8000` |

服务完全离线运行，不连接任何外部服务。

## API 地址与端口

- 服务地址：`http://localhost:8000`（改了 `HOST_PORT` 则对应替换端口）
- 健康检查：`GET http://localhost:8000/health`
- 交互式文档（Swagger UI）：`http://localhost:8000/docs`
- 拼版接口：`POST http://localhost:8000/api/v1/impose`
- 章节分帖拼版接口：`POST http://localhost:8000/api/v1/impose/chapters`
- 重印复用接口：`POST http://localhost:8000/api/v1/impose/reprint`
- 印张抽检接口：`POST http://localhost:8000/api/v1/impose/inspect`
- 机台版面接口：`POST http://localhost:8000/api/v1/impose/press-layout`
- 瑕疵定位接口：`POST http://localhost:8000/api/v1/impose/locate-defects`
- 墨区着墨面积接口：`POST http://localhost:8000/api/v1/impose/ink-zones`
- 外裁/折缝安全检查接口：`POST http://localhost:8000/api/v1/impose/trim-safety`
- 双面拼版校样（PDF 下载）：`POST http://localhost:8000/api/v1/impose/proof.pdf`
- 订针计划接口：`POST http://localhost:8000/api/v1/impose/staple-plan`
- 原纸备料接口：`POST http://localhost:8000/api/v1/impose/stock-plan`
- 骑马订爬移补偿接口：`POST http://localhost:8000/api/v1/impose/creep-plan`

## 接口说明

### 请求

`POST /api/v1/impose`，`Content-Type: application/json`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `total_pages` | 整数 | ≥ 1 | 总页数（正整数） |
| `max_sheets_per_signature` | 整数 | ≥ 1 | 每帖最多纸张数；每帖最多容纳其 **4 倍**页数 |
| `binding` | 字符串 | `left` / `right` | 装订方向：左装订 / 右装订 |

```bash
curl -X POST http://localhost:8000/api/v1/impose \
  -H "Content-Type: application/json" \
  -d '{"total_pages": 16, "max_sheets_per_signature": 4, "binding": "left"}'
```

### 响应

返回帖号 `signature_index` 与帖内纸张序号 `sheet_index`（从 1 开始，1 为最外张），
以及每张纸正面 `front` / 背面 `back` 的左 `left` / 右 `right` 页码；空白页为 `null`。

```json
{
  "total_pages": 16,
  "max_sheets_per_signature": 4,
  "binding": "left",
  "signature_count": 1,
  "signatures": [
    {
      "signature_index": 1,
      "sheet_count": 4,
      "page_count_padded": 16,
      "sheets": [
        {
          "sheet_index": 1,
          "front": { "left": 16, "right": 1 },
          "back":  { "left": 2,  "right": 15 }
        },
        {
          "sheet_index": 2,
          "front": { "left": 14, "right": 3 },
          "back":  { "left": 4,  "right": 13 }
        }
      ]
    }
  ]
}
```

> 实际响应会列出全部 4 张纸，上例只展示前 2 张。

### 拼版规则

1. 按原页顺序分帖，每帖最多容纳 `4 × max_sheets_per_signature` 页；除末帖外各帖均装满。
2. 仅**末帖**在尾部补空白页至 4 的倍数，空白位置页码为 `null`。
3. 左装订（`left`）最外张：
   - 正面（`front`）：左 = 末页，右 = 首页；
   - 背面（`back`）：左 = 次页，右 = 倒数第二页；
   - 之后逐张向内递推（帖页数为 `n`，纸张从外向内序号为 `k = 0,1,2...`，四个页位在帖内的位置索引从 0 计分别为：正左 `n-1-2k`、正右 `2k`、背左 `2k+1`、背右 `n-2-2k`，取出的即为该位置的全局页码，补齐位置为 `null`）。
4. 右装订（`right`）为镜像装订：将左装订结果的**左右页位整体交换**（正反关系不变）。

### 非法参数（4xx）

参数缺失、类型错误、`total_pages` / `max_sheets_per_signature` 小于 1、`binding` 不是
`left`/`right`、包含未定义字段时，均返回 `422 Unprocessable Entity`：

```json
{
  "detail": [
    { "type": "greater_than_equal", "loc": ["body", "total_pages"], "msg": "Input should be greater than or equal to 1" }
  ]
}
```

## 机台版面（POST /api/v1/impose/press-layout）

在 `/api/v1/impose` 的**相同分帖、末帖补空白与左/右装订页序规则**之上，为每个页位补充
机台落版所需的纸面尺寸、左上角坐标与旋转角度。本地访问地址
`http://localhost:8000/api/v1/impose/press-layout`（改了 `HOST_PORT` 则对应替换端口）。

页位几何由统一模块 `app/press_geometry.py` 提供，四个接口共用同一套**双向坐标变换**：
装订方向与长/短边翻转决定每个**实际槽位**上的页码、槽位原点与 `0°/180°` 旋转；
`press-layout` 据此生成页位，`locate-defects` 用逆变换把纸面点还原为阅读方向页内点，
`ink-zones` 与 `trim-safety` 用正变换把页内矩形映射为纸面矩形。中缝与空白页位仍按
各接口既有语义处理（中缝单独标记 / 空白跳过），各接口响应字段不变。

### 请求

`POST /api/v1/impose/press-layout`，`Content-Type: application/json`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `total_pages` | 整数 | ≥ 1 | 总页数（正整数） |
| `max_sheets_per_signature` | 整数 | ≥ 1 | 每帖最多纸张数；每帖最多容纳其 **4 倍**页数 |
| `binding` | 字符串 | `left` / `right` | 装订方向：左装订 / 右装订 |
| `page_width_mm` | 数值 | 正数（有限值） | 单页宽度（mm） |
| `page_height_mm` | 数值 | 正数（有限值） | 单页高度（mm） |
| `gutter_mm` | 数值 | 非负数（有限值） | 中缝宽度（mm），允许为 `0` |
| `duplex_flip` | 字符串 | `long` / `short` | 双面翻转：`long`=长边翻转，`short`=短边翻转 |

```bash
curl -X POST http://localhost:8000/api/v1/impose/press-layout \
  -H "Content-Type: application/json" \
  -d '{
    "total_pages": 4,
    "max_sheets_per_signature": 1,
    "binding": "left",
    "page_width_mm": 210,
    "page_height_mm": 297,
    "gutter_mm": 10,
    "duplex_flip": "long"
  }'
```

### 坐标与翻转规则

- **纸面尺寸**：每张纸的纸面宽 `paper_width_mm = 2 × page_width_mm + gutter_mm`
  （两倍页宽加中缝），纸面高 `paper_height_mm = page_height_mm`（等于页高）；
  顶层与每帖都给出纸面尺寸。
- **坐标系**：以纸张**左上角为原点**，x 轴向右、y 轴向下，单位 mm。
  - 正面左槽位于 `x = 0`，右槽位于 `x = page_width_mm + gutter_mm`，两槽 `y = 0`；
  - `x_mm` / `y_mm` 为页位**未旋转时**的左上角坐标。
- **正反面**：
  - 正面（`front`）左右槽均为旋转 `0°`；
  - 背面（`back`）`long`（长边翻转）模式**交换左右槽**（页码随新槽位，坐标按新槽位给出），
    各页位旋转 `0°`；
  - 背面（`back`）`short`（短边翻转）模式**保持槽位**（坐标不变），各页位绕**页位中心**
    旋转 `180°`。页位与槽位等大，0°/180° 旋转都不改变外接框，故左上角坐标与槽位一致。
- **空白页位**：补齐的空白页位整体为 `null`（不含坐标），规则与 `/api/v1/impose` 相同。

### 响应

按帖号 `signature_index`、张号 `sheet_index`（从 1 开始，1 为最外张）返回；每个页位给出
`page`（页码）、`x_mm` / `y_mm`（左上角坐标）、`rotation_deg`（绕页位中心的旋转角 `0` 或 `180`）。

上例（4 页、页宽 210、中缝 10，纸面 430 × 297，`long`）响应：

```json
{
  "total_pages": 4,
  "max_sheets_per_signature": 1,
  "binding": "left",
  "page_width_mm": 210.0,
  "page_height_mm": 297.0,
  "gutter_mm": 10.0,
  "duplex_flip": "long",
  "paper_width_mm": 430.0,
  "paper_height_mm": 297.0,
  "signature_count": 1,
  "signatures": [
    {
      "signature_index": 1,
      "sheet_count": 1,
      "page_count_padded": 4,
      "paper_width_mm": 430.0,
      "paper_height_mm": 297.0,
      "sheets": [
        {
          "sheet_index": 1,
          "front": {
            "left":  { "page": 4, "x_mm": 0.0,   "y_mm": 0.0, "rotation_deg": 0 },
            "right": { "page": 1, "x_mm": 220.0, "y_mm": 0.0, "rotation_deg": 0 }
          },
          "back": {
            "left":  { "page": 3, "x_mm": 0.0,   "y_mm": 0.0, "rotation_deg": 0 },
            "right": { "page": 2, "x_mm": 220.0, "y_mm": 0.0, "rotation_deg": 0 }
          }
        }
      ]
    }
  ]
}
```

同一请求若改为 `"duplex_flip": "short"`、`"gutter_mm": 0`（纸面 420 × 297），背面将保持
左装订页序（背左 = 2、背右 = 3），两个页位的 `rotation_deg` 均为 `180`、`x_mm` 分别为
`0.0` 与 `210.0`。

### 非法参数（4xx）

除与 `/api/v1/impose` 相同的校验（`total_pages` / `max_sheets_per_signature` / `binding`、
未定义字段等）外，`page_width_mm` / `page_height_mm` 非正数（含 `0`、负数、`NaN`、
`Infinity`）、`gutter_mm` 为负数或非有限值、`duplex_flip` 不是 `long`/`short` 时，
均返回 `422 Unprocessable Entity`。

## 瑕疵定位（POST /api/v1/impose/locate-defects）

在机台版面的**相同分帖、页序、槽位与旋转规则**之上，把纸面上检测到的瑕疵点反查为
**原稿页码**与**阅读方向的页内坐标**，用于质检系统定位缺陷来源。本地访问地址
`http://localhost:8000/api/v1/impose/locate-defects`（改了 `HOST_PORT` 则对应替换端口）。

### 请求

`POST /api/v1/impose/locate-defects`，`Content-Type: application/json`

机台版面的全部参数原样沿用（`total_pages` / `max_sheets_per_signature` / `binding` /
`page_width_mm` / `page_height_mm` / `gutter_mm` / `duplex_flip`，约束相同），另加：

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `defects` | 对象数组 | 非空 | 瑕疵点列表，逐点定位 |
| `defects[].signature_index` | 整数 | ≥ 1 且不超过帖数 | 帖号，从 1 开始 |
| `defects[].sheet_index` | 整数 | ≥ 1 且不超过该帖张数 | 帖内张号，从 1 开始（1 为最外张） |
| `defects[].side` | 字符串 | `front` / `back` | 正反面：`front`=正面，`back`=背面 |
| `defects[].x_mm` | 数值 | 有限值，且在纸面宽度内 | 瑕疵点 x 坐标（mm），以**纸面左上角**为原点、向右为正 |
| `defects[].y_mm` | 数值 | 有限值，且在纸面高度内 | 瑕疵点 y 坐标（mm），以**纸面左上角**为原点、向下为正 |

```bash
curl -X POST http://localhost:8000/api/v1/impose/locate-defects \
  -H "Content-Type: application/json" \
  -d '{
    "total_pages": 4,
    "max_sheets_per_signature": 1,
    "binding": "left",
    "page_width_mm": 210,
    "page_height_mm": 297,
    "gutter_mm": 10,
    "duplex_flip": "long",
    "defects": [
      {"signature_index": 1, "sheet_index": 1, "side": "front", "x_mm": 100, "y_mm": 50},
      {"signature_index": 1, "sheet_index": 1, "side": "back",  "x_mm": 250, "y_mm": 40},
      {"signature_index": 1, "sheet_index": 1, "side": "front", "x_mm": 215, "y_mm": 100}
    ]
  }'
```

### 定位规则

- **坐标系**：与机台版面一致——纸面左上角为原点，x 向右、y 向下，单位 mm；
  纸面宽 `2 × page_width_mm + gutter_mm`、高 `page_height_mm`，纸面边缘上的点有效。
- **槽位判定**：左槽 `x ∈ [0, page_width_mm)`，中缝 `x ∈ [page_width_mm,
  page_width_mm + gutter_mm)`（`gutter_mm = 0` 时无中缝），右槽
  `x ∈ [page_width_mm + gutter_mm, paper_width_mm]`。
- **页内坐标**：落在页内时，先取槽内坐标（减去槽位左上角），再按该页位的旋转角
  还原为**阅读方向**（从该页自身左上角起算）：
  - 正面与 `long`（长边翻转）背面旋转 `0°`，页内坐标即槽内坐标；
    `long` 背面按**交换后的槽位**定位（与机台版面一致）；
  - `short`（短边翻转）背面各页位绕自身中心旋转 `180°`，页内坐标需逆转 180°：
    `page_x = page_width_mm − 槽内 x`，`page_y = page_height_mm − 槽内 y`。
- **中缝与空白页位**：落在中缝的点标记 `location = "gutter"`，落在补齐空白页位的点
  标记 `location = "blank"`；两者均**不返回页码**（`page` 与页内坐标均为 `null`）。

### 响应

按请求 `defects` 顺序逐点返回（`defect_index` 从 1 开始）；顶层回显机台版面参数、
纸面尺寸与 `defect_count`。上例（4 页、左装订、纸面 430 × 297、`long`）响应：

```json
{
  "total_pages": 4,
  "max_sheets_per_signature": 1,
  "binding": "left",
  "page_width_mm": 210.0,
  "page_height_mm": 297.0,
  "gutter_mm": 10.0,
  "duplex_flip": "long",
  "paper_width_mm": 430.0,
  "paper_height_mm": 297.0,
  "defect_count": 3,
  "defects": [
    { "defect_index": 1, "location": "page",   "page": 4,    "page_x_mm": 100.0, "page_y_mm": 50.0 },
    { "defect_index": 2, "location": "page",   "page": 2,    "page_x_mm": 30.0,  "page_y_mm": 40.0 },
    { "defect_index": 3, "location": "gutter", "page": null, "page_x_mm": null,  "page_y_mm": null }
  ]
}
```

其中：点 1 落在正面左槽（第 4 页），页内坐标即槽内坐标；点 2 落在 `long` 背面交换后的
右槽（第 2 页，槽位 x=220，页内 x = 250 − 220 = 30）；点 3 的 x=215 落在中缝
`[210, 220)` 内，标记 `gutter` 且不返回页码。若改为 `short` 翻转，点 2 所在背面保持
槽位（背左 = 2、背右 = 3）且页内坐标逆转 180°。

### 非法参数（4xx）

机台版面参数的校验与 `/api/v1/impose/press-layout` 完全一致；此外 `defects` 为空、
瑕疵点缺字段或含未定义字段、`side` 不是 `front`/`back`、坐标为非有限值（`NaN` /
`Infinity`）、**坐标越出纸面**（含负坐标）、**帖号或张号无效**（小于 1 或超出实际
帖数/张数）时，均返回 `422 Unprocessable Entity`。

## 墨区着墨面积（POST /api/v1/impose/ink-zones）

在机台版面的**相同分帖、页序、槽位与旋转规则**之上，统计各墨键墨区的 CMYK 等效着墨面积，
用于印刷机墨量预设。本地访问地址 `http://localhost:8000/api/v1/impose/ink-zones`
（改了 `HOST_PORT` 则对应替换端口）。

### 请求

`POST /api/v1/impose/ink-zones`，`Content-Type: application/json`

机台版面的全部参数原样沿用（`total_pages` / `max_sheets_per_signature` / `binding` /
`page_width_mm` / `page_height_mm` / `gutter_mm` / `duplex_flip`，约束相同），另加：

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `zone_count` | 整数 | 1～16 | 纸面宽度方向的**等宽墨区数量** |
| `copies` | 整数 | ≥ 1 | 印数（正整数）；返回的着墨面积已乘该印数 |
| `page_inks` | 对象数组 | 允许为空 | 各页的页内矩形墨稿；**空白页无需给出** |
| `page_inks[].page` | 整数 | 1～`total_pages`，同页只能出现一次 | 页码 |
| `page_inks[].rectangles` | 对象数组 | 非空 | 该页的页内矩形，**互不重叠**且**完整落在页面内**（允许贴边） |
| `rectangles[].x_mm` / `y_mm` | 数值 | ≥ 0、有限值 | 矩形**左上角**在页内的坐标（mm），以**页面左上角**为原点、向右/向下为正 |
| `rectangles[].width_mm` / `height_mm` | 数值 | 正数、有限值 | 矩形宽、高（mm）；`x + width ≤ page_width_mm`、`y + height ≤ page_height_mm` |
| `rectangles[].cyan` / `magenta` / `yellow` / `black` | 数值 | 0～1 | 青/品/黄/黑四通道覆盖率（`1` = 100%） |

```bash
curl -X POST http://localhost:8000/api/v1/impose/ink-zones \
  -H "Content-Type: application/json" \
  -d '{
    "total_pages": 4,
    "max_sheets_per_signature": 1,
    "binding": "left",
    "page_width_mm": 210,
    "page_height_mm": 297,
    "gutter_mm": 10,
    "duplex_flip": "long",
    "zone_count": 5,
    "copies": 500,
    "page_inks": [
      {"page": 1, "rectangles": [
        {"x_mm": 0, "y_mm": 0, "width_mm": 100, "height_mm": 297,
         "cyan": 0.2, "magenta": 0.1, "yellow": 0, "black": 0.05}
      ]}
    ]
  }'
```

### 映射与拆分规则

- **页位映射**：每个页内矩形按其页码所在页位（与机台版面完全一致：分帖、左/右装订镜像、
  `long` 背面交换槽位、`short` 背面保持槽位）映射到纸面：
  - 页位旋转 `0°`（正面与 `long` 背面）：纸面矩形左上角 = 槽位左上角 + 页内左上角，宽高不变；
  - 页位旋转 `180°`（`short` 背面）：绕页位中心旋转——
    纸面左上角 = `(槽位 x + 页宽 − x − width, 页高 − y − height)`，宽高不变。
- **等宽墨区**：墨区沿纸面宽度方向等分为 `zone_count` 个竖条，
  墨区宽 `zone_width_mm = paper_width_mm / zone_count`，
  墨区序号 `zone_index` 从纸面**左侧起**从 1 开始；墨区在整个纸面高度内贯通。
- **跨区拆分**：矩形与墨区按**交叠面积**（交叠宽 × 矩形高）拆分；落在中缝内的部分不计
  （页内矩形完整落在页面内，只有跨槽映射时才可能出现此类零贡献段）。
- **等效着墨面积**：某墨区某通道的结果为
  `Σ(交叠面积 × 矩形该通道覆盖率) × copies`，单位 mm²；同一墨区内多个矩形、多页
  （正反面互不重合）的贡献直接累加。
- **空白页不计**：末帖补齐的空白页位不参与统计；请求中也不需要为空白页给墨稿。
  某一面（正面/背面）所有墨区四通道全为 0 时，该面键（`front` / `back`）整体**缺省**；
  输出的墨区内仅列出至少有一个通道结果为正的墨区，按 `zone_index` 升序。

### 响应

顶层回显机台版面参数、纸面尺寸、墨区数量与墨区宽 `zone_width_mm`、印数 `copies`；
按帖（`signature_index`）、张（`sheet_index`，1 为最外张）、正反面给出墨区结果，
每个墨区含 `zone_index` 与四通道的等效着墨面积乘印数（`cyan_mm2` / `magenta_mm2` /
`yellow_mm2` / `black_mm2`，mm²）。上例（4 页、左装订、纸面 430 × 297、5 个墨区各宽 86）
中，第 1 页位于正面右槽（槽位 x=220），页内 0～100 mm 映射到纸面 220～320 mm，
跨第 3、4 墨区（交叠宽 38、62 mm）：

```json
{
  "total_pages": 4,
  "max_sheets_per_signature": 1,
  "binding": "left",
  "page_width_mm": 210.0,
  "page_height_mm": 297.0,
  "gutter_mm": 10.0,
  "duplex_flip": "long",
  "paper_width_mm": 430.0,
  "paper_height_mm": 297.0,
  "zone_count": 5,
  "zone_width_mm": 86.0,
  "copies": 500,
  "signature_count": 1,
  "signatures": [
    {
      "signature_index": 1,
      "sheet_count": 1,
      "page_count_padded": 4,
      "sheets": [
        {
          "sheet_index": 1,
          "front": [
            {"zone_index": 3, "cyan_mm2": 1128600.0, "magenta_mm2": 564300.0,
             "yellow_mm2": 0.0, "black_mm2": 282150.0},
            {"zone_index": 4, "cyan_mm2": 1841400.0, "magenta_mm2": 920700.0,
             "yellow_mm2": 0.0, "black_mm2": 460350.0}
          ]
        }
      ]
    }
  ]
}
```

例如第 3 墨区青通道：交叠面积 `38 × 297 = 11286 mm²`，等效着墨面积
`11286 × 0.2 = 2257.2 mm²`，乘印数 500 得 `1128600 mm²`。背面四通道均为 0，故 `back` 键缺省。

### 非法参数（4xx）

机台版面参数的校验与 `/api/v1/impose/press-layout` 完全一致；此外：

- `zone_count` 不在 1～16、`copies` 小于 1（或非整数）；
- **页码无效**：`page_inks[].page` 小于 1、超过 `total_pages`，或同一页码出现两次；
- **矩形越界**：`x_mm` / `y_mm` 为负或非有限值、`width_mm` / `height_mm` 非正或非有限值、
  `x + width > page_width_mm` 或 `y + height > page_height_mm`（矩形未完整落在页面内）；
- **同页矩形重叠**：同一页的两个矩形存在正面积交叠（仅边相切不算重叠）；
- 任一通道覆盖率不在 0～1、矩形/页缺字段或含未定义字段；

以上均返回 `422 Unprocessable Entity`。

## 外裁/折缝安全检查（POST /api/v1/impose/trim-safety）

在机台版面的**相同分帖、页序、槽位与旋转规则**之上，把各页**阅读方向**的受保护内容矩形映射到纸面，
逐张逐面核对其与**外裁边**、**折缝**的安全距离，用于上机前检查重要内容（文字、二维码、人脸等）是否
会被裁掉或压到折缝。本地访问地址 `http://localhost:8000/api/v1/impose/trim-safety`
（改了 `HOST_PORT` 则对应替换端口）。

### 请求

`POST /api/v1/impose/trim-safety`，`Content-Type: application/json`

机台版面的全部参数原样沿用（`total_pages` / `max_sheets_per_signature` / `binding` /
`page_width_mm` / `page_height_mm` / `gutter_mm` / `duplex_flip`，约束相同），另加：

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `outer_trim_mm` | 数值 | ≥ 0（有限值） | **外裁安全距离**（mm）；用于中缝以外的三边 |
| `fold_safety_mm` | 数值 | ≥ 0（有限值） | **折缝安全距离**（mm）；用于中缝侧 |
| `page_protected` | 对象数组 | 允许为空 | 按**实际页码**给出的各页受保护内容矩形；**空白页无需给出** |
| `page_protected[].page` | 整数 | 1～`total_pages`，同页只能出现一次 | 页码 |
| `page_protected[].rectangles` | 对象数组 | 非空 | 该页阅读方向的受保护矩形，**完整落在页面内**（允许贴边）；同页矩形允许相互交叠 |
| `rectangles[].x_mm` / `y_mm` | 数值 | ≥ 0、有限值 | 矩形**左上角**在页内的坐标（mm），以**页面左上角**为原点、向右/向下为正 |
| `rectangles[].width_mm` / `height_mm` | 数值 | 正数、有限值 | 矩形宽、高（mm）；`x + width ≤ page_width_mm`、`y + height ≤ page_height_mm` |

```bash
curl -X POST http://localhost:8000/api/v1/impose/trim-safety \
  -H "Content-Type: application/json" \
  -d '{
    "total_pages": 4,
    "max_sheets_per_signature": 1,
    "binding": "left",
    "page_width_mm": 210,
    "page_height_mm": 297,
    "gutter_mm": 0,
    "duplex_flip": "long",
    "outer_trim_mm": 3,
    "fold_safety_mm": 7,
    "page_protected": [
      {"page": 1, "rectangles": [
        {"x_mm": 10, "y_mm": 20, "width_mm": 120, "height_mm": 60}
      ]},
      {"page": 4, "rectangles": [
        {"x_mm": 0, "y_mm": 0, "width_mm": 210, "height_mm": 297}
      ]}
    ]
  }'
```

### 映射与检查规则

- **页位映射**：每个受保护矩形按其页码所在页位（与机台版面完全一致：分帖、左/右装订镜像、
  `long` 背面交换槽位、`short` 背面保持槽位并旋转 180°）映射到纸面坐标：
  - 页位旋转 `0°`（正面与 `long` 背面）：纸面矩形左上角 = 槽位左上角 + 页内左上角，宽高不变；
  - 页位旋转 `180°`（`short` 背面）：绕页位中心旋转——
    纸面左上角 = `(槽位 x + 页宽 − x − width, 页高 − y − height)`，宽高不变。
- **折缝线**：纸面（中缝）中心线 `paper_width_mm / 2 = page_width_mm + gutter_mm / 2`。
- **四条安全线**（矩形边与安全线比较，**贴线视为合格**，仅严格越线才记违规）：
  - **中缝侧**（`edge = "fold"`）：左槽看矩形**右边**、右槽看矩形**左边**，
    与折缝线保持 `fold_safety_mm`；
  - **其余三边**按 `outer_trim_mm`：纸面**顶边**（`edge = "top"`）、
    纸面**底边**（`edge = "bottom"`），以及**纸面外侧竖边**（`edge = "outer"`，
    左槽看靠左纸边的矩形左边、右槽看靠右纸边的矩形右边）。
- **空白页跳过**：末帖补齐的空白页位不参与检查，请求中也不需要给空白页内容；
  `page_protected` 为空（所有页都没有受保护内容）时违规列表为空。
- 一个矩形同时越过多条安全线时，**逐边各记一条**违规，同一矩形的边顺序固定为
  `top`、`bottom`、`outer`、`fold`；整体按帖号、张号、正反面（front → back）、
  左右槽与请求中的矩形顺序排列。

### 响应

顶层回显机台版面参数、纸面尺寸、两个安全距离与 `violation_count`；`violations` 逐处给出帖号
`signature_index`、张号 `sheet_index`（1 为最外张）、正反面 `side`、原稿页码 `page`、
违规边 `edge` 与映射后的**纸面矩形** `rectangle`（左上角坐标与宽高，mm，纸面左上角为原点）。

上例（纸面 420 × 297、无中缝、折缝线 x=210、左装订）：

- 第 1 页在正面右槽（槽位 x=210），页内 `(10,20,120,60)` 映射到纸面 `(220,20,120,60)`：
  左缘 220 距折缝线 10 mm ≥ 7，其余三边距纸边也都 ≥ 3，**不违规**；
- 第 4 页在正面左槽，整页出血矩形铺满纸面 `(0,0,210,297)`：四边全部越线。

```json
{
  "total_pages": 4,
  "max_sheets_per_signature": 1,
  "binding": "left",
  "page_width_mm": 210.0,
  "page_height_mm": 297.0,
  "gutter_mm": 0.0,
  "duplex_flip": "long",
  "paper_width_mm": 420.0,
  "paper_height_mm": 297.0,
  "outer_trim_mm": 3.0,
  "fold_safety_mm": 7.0,
  "violation_count": 4,
  "violations": [
    {"signature_index": 1, "sheet_index": 1, "side": "front", "page": 4, "edge": "top",
     "rectangle": {"x_mm": 0.0, "y_mm": 0.0, "width_mm": 210.0, "height_mm": 297.0}},
    {"signature_index": 1, "sheet_index": 1, "side": "front", "page": 4, "edge": "bottom",
     "rectangle": {"x_mm": 0.0, "y_mm": 0.0, "width_mm": 210.0, "height_mm": 297.0}},
    {"signature_index": 1, "sheet_index": 1, "side": "front", "page": 4, "edge": "outer",
     "rectangle": {"x_mm": 0.0, "y_mm": 0.0, "width_mm": 210.0, "height_mm": 297.0}},
    {"signature_index": 1, "sheet_index": 1, "side": "front", "page": 4, "edge": "fold",
     "rectangle": {"x_mm": 0.0, "y_mm": 0.0, "width_mm": 210.0, "height_mm": 297.0}}
  ]
}
```

### 非法参数（4xx）

机台版面参数的校验与 `/api/v1/impose/press-layout` 完全一致；此外：

- `outer_trim_mm` / `fold_safety_mm` 为负或非有限值；
- **页码无效**：`page_protected[].page` 小于 1、超过 `total_pages`（或不是整数），或同一页码出现两次；
- **矩形越出页面**：`x_mm` / `y_mm` 为负或非有限值、`width_mm` / `height_mm` 非正或非有限值、
  `x + width > page_width_mm` 或 `y + height > page_height_mm`（矩形未完整落在页面内）；
- 矩形/页缺字段或含未定义字段；

以上均返回 `422 Unprocessable Entity`。注意：**矩形越出页内是请求错误（422）**；
矩形在页内合法、映射纸面后越过安全线则是正常的检查结果（200 + `violations`）。

## 双面拼版校样 PDF（POST /api/v1/impose/proof.pdf）

在机台版面的计算结果上直接绘制可下载的**双面拼版校样 PDF**，用于上机前核对页序、帖号、张号与
落版方向。本地访问地址 `http://localhost:8000/api/v1/impose/proof.pdf`
（改了 `HOST_PORT` 则对应替换端口）。

### 请求

`POST /api/v1/impose/proof.pdf`，`Content-Type: application/json`，**请求参数与
`/api/v1/impose/press-layout` 完全相同**：

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `total_pages` | 整数 | ≥ 1，且总印张数 ≤ 100 | 总页数（正整数） |
| `max_sheets_per_signature` | 整数 | ≥ 1 | 每帖最多纸张数；每帖最多容纳其 **4 倍**页数 |
| `binding` | 字符串 | `left` / `right` | 装订方向：左装订 / 右装订 |
| `page_width_mm` | 数值 | 正数（有限值） | 单页宽度（mm） |
| `page_height_mm` | 数值 | 正数（有限值） | 单页高度（mm） |
| `gutter_mm` | 数值 | 非负数（有限值） | 中缝宽度（mm），允许为 `0` |
| `duplex_flip` | 字符串 | `long` / `short` | 双面翻转：`long`=长边翻转，`short`=短边翻转 |

### 下载示例

用 `curl -o`（或 `--output`）把响应保存为本地文件；响应头
`Content-Type: application/pdf`、`Content-Disposition: attachment; filename="proof.pdf"`：

```bash
curl -X POST http://localhost:8000/api/v1/impose/proof.pdf \
  -H "Content-Type: application/json" \
  -d '{
    "total_pages": 16,
    "max_sheets_per_signature": 4,
    "binding": "left",
    "page_width_mm": 210,
    "page_height_mm": 297,
    "gutter_mm": 10,
    "duplex_flip": "long"
  }' \
  -o proof.pdf
```

启动服务后（`docker compose up -d --build`），在浏览器打开
<http://localhost:8000/docs>，找到 **“双面拼版校样：下载 proof.pdf”**，
点击 **Try it out** 填入参数后 **Execute**，也可直接下载 `proof.pdf`；
健康检查地址为 <http://localhost:8000/health>。

### PDF 内容

- **页数**：每张印张依次生成两页，顺序为**正面（front）→ 背面（back）**，按帖号升序、
  帖内张号从外到内排列；N 张印张即 2N 页。
- **纸面尺寸**：每页 MediaBox 与机台版面计算结果一致——
  宽 `2 × page_width_mm + gutter_mm`、高 `page_height_mm`（单位 mm）。
- **页位标注**：每个页位居中标注**页码**大字，下方标注“第 N 帖 · 第 M 张 · 正面/背面”；
  末帖补白等空白页位标注灰色的**“空白”**，同样带帖号、张号。
- **中缝分隔线**：沿中缝中心（`page_width_mm + gutter_mm / 2`）画一条竖向虚线；
  `gutter_mm = 0` 时即左右槽分界线。
- **与机台版面一致**：页序、槽位坐标与旋转角完全沿用 `/api/v1/impose/press-layout`：
  - press-layout 以**左上角为原点**的毫米坐标换算为 PDF 的**左下角**坐标
    （`y_pdf = paper_height_mm − y_mm`，再乘 mm→pt）；
  - 左装订 / 右装订的左右镜像页序一致；
  - `long`（长边翻转）背面左右槽交换、页位不旋转；
  - `short`（短边翻转）背面保持槽位，各页位绕自身中心旋转 **180°**（校样中页码、
    文字一并倒置，与实际短边翻转落版朝向相同）。

### 非法参数与张数上限（4xx）

- 参数校验与 `/api/v1/impose/press-layout` 完全一致：尺寸非正数 / 非有限值、`gutter_mm`
  为负、`binding` / `duplex_flip` 取值非法、未定义字段等均返回 `422`。
- **单次最多生成 100 张印张**（即最多 400 页，PDF 最多 200 页）；总页数对应印张数
  超过 100 张时返回 `422 Unprocessable Entity`，并在错误信息中给出本次张数与页数。
  400 页（恰好 100 张）仍可正常下载。

## 订针计划（POST /api/v1/impose/staple-plan）

在 `/api/v1/impose` 的**相同分帖结果**（帖数、每帖张数与末帖补白）之上，为每个帖规划骑马订订针的
整数毫米针位，用于装订工序下针。针位规划只取决于页高与禁针要求，与装订方向无关（`binding` 仍照常传入）。
本地访问地址 `http://localhost:8000/api/v1/impose/staple-plan`（改了 `HOST_PORT` 则对应替换端口）。

### 请求

`POST /api/v1/impose/staple-plan`，`Content-Type: application/json`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `total_pages` | 整数 | ≥ 1 | 总页数（正整数），沿用普通拼版的分帖参数 |
| `max_sheets_per_signature` | 整数 | ≥ 1 | 每帖最多纸张数；每帖最多容纳其 **4 倍**页数 |
| `binding` | 字符串 | `left` / `right` | 装订方向：左装订 / 右装订 |
| `page_height_mm` | 数值 | 50～1000（有限值） | 页高（mm） |
| `staple_count` | 整数 | 2～4 | 每帖订针数（严格整数，不接受小数/布尔值） |
| `top_margin_mm` | 数值 | ≥ 0（有限值） | 上留边（mm）；上留边 + 下留边须**小于**页高 |
| `bottom_margin_mm` | 数值 | ≥ 0（有限值） | 下留边（mm）；上留边 + 下留边须**小于**页高 |
| `min_spacing_mm` | 数值 | ≥ 0（有限值） | 相邻订针的最小针距（mm） |
| `forbidden_zones` | 对象数组 | 允许为空（可省略） | 按帖号给出的**禁针闭区间**；无禁针要求的帖无需给出 |
| `forbidden_zones[].signature_index` | 整数 | 1～帖数，每帖至多 1 项 | 帖号，从 1 开始 |
| `forbidden_zones[].intervals` | 对象数组 | 非空 | 该帖禁针闭区间 `[start_mm, end_mm]` 列表 |
| `intervals[].start_mm` / `end_mm` | 数值 | `0 ≤ start ≤ end ≤ 页高` | 禁针闭区间端点（mm），以**页顶为原点**、向下为正 |

```bash
curl -X POST http://localhost:8000/api/v1/impose/staple-plan \
  -H "Content-Type: application/json" \
  -d '{
    "total_pages": 8,
    "max_sheets_per_signature": 4,
    "binding": "left",
    "page_height_mm": 100,
    "staple_count": 3,
    "top_margin_mm": 14,
    "bottom_margin_mm": 14,
    "min_spacing_mm": 10,
    "forbidden_zones": [
      {"signature_index": 1,
       "intervals": [{"start_mm": 40, "end_mm": 42}, {"start_mm": 88, "end_mm": 92}]}
    ]
  }'
```

### 针位规划规则

- **整数毫米刻度**：订针位置限于页高 `0..page_height_mm` 内的整数毫米刻度
  （页高非整数时，取到不超过页高的刻度为止），以页顶为原点、向下为正。
- **避开留边**：针位严格满足 `上留边 < y < 页高 − 下留边`（留边边界上的刻度不可下针）；
  上下留边为 0 时，页高两端的刻度（0 与页高）同样不可下针。
- **避开禁区**：针位不得落在任一禁针**闭区间** `[start_mm, end_mm]` 内——
  与端点重合的整数刻度同样禁针；禁区只作用于指定的帖，其他帖不受影响。
- **最小针距**：同帖针位自上而下严格递增，相邻针距（`p[i+1] − p[i]`）不小于 `min_spacing_mm`。
- **理想针位**：第 `i` 个（`i = 1..staple_count`）理想针位为

  ```
  上留边 + i × (页高 − 上留边 − 下留边) / (订针数 + 1)
  ```

- **择优顺序**：在全部可行的递增针位序列中，依次
  1. **最小化最大绝对偏差**（max_i |p[i] − 理想针位[i]|）；
  2. 并列时**最小化偏差总和**（Σ|p[i] − 理想针位[i]|）；
  3. 仍并列时取**针位序列字典序最小**（自上而下逐位比较，首位可小则小）。

### 响应

逐帖返回 `signature_index`、沿用普通拼版的 `sheet_count` / `page_count_padded`，以及
`staple_positions_mm`（自上而下递增的整数毫米针位）与 `max_deviation_mm`（本帖最大绝对偏差）。

上例（页高 100、上下留边各 14、订 3 针，理想针位恰为 32/50/68；禁区未覆盖这三个刻度）响应：

```json
{
  "total_pages": 8,
  "max_sheets_per_signature": 4,
  "binding": "left",
  "page_height_mm": 100.0,
  "staple_count": 3,
  "top_margin_mm": 14.0,
  "bottom_margin_mm": 14.0,
  "min_spacing_mm": 10.0,
  "signature_count": 1,
  "signatures": [
    {
      "signature_index": 1,
      "sheet_count": 2,
      "page_count_padded": 8,
      "staple_positions_mm": [32, 50, 68],
      "max_deviation_mm": 0.0
    }
  ]
}
```

### 非法参数与无可行排列（4xx）

- 分帖参数非法（`total_pages` / `max_sheets_per_signature` 小于 1、`binding` 取值非法等）；
- 页高不在 50～1000、`staple_count` 不在 2～4 或不是整数、留边/最小针距为负或非有限值、
  上下留边之和不小于页高；
- 禁针区间帖号超出实际帖数、同一帖号重复给出、区间端点为负、`start > end` 或超出页高；
- **某帖无可行排列**（如可用刻度全部落入禁区、或任意两个合法刻度的间距都小于最小针距）：
  返回 `422 Unprocessable Entity`，错误信息指出帖号，例如
  `Value error, 第 2 帖无可行订针排列`。

## 原纸备料（POST /api/v1/impose/stock-plan）

根据成品印张尺寸与库存原纸规格计算各规格单张出数，并在库存内选择总面积最小的原纸领用组合，用于裁切备料。
本地访问地址 `http://localhost:8000/api/v1/impose/stock-plan`（改了 `HOST_PORT` 则对应替换端口）。

需求与成品尺寸沿用既有拼版链路：

- **每册印张数**沿用 `/api/v1/impose` 的分帖参数（总页数、每帖最多纸张数、装订方向），
  含末帖补白张（每张 4 页）；**总需求 = 每册印张数 × 印数**。
- **成品印张尺寸**沿用机台版面：宽 `sheet_width_mm = 2 × page_width_mm + gutter_mm`、
  高 `sheet_height_mm = page_height_mm`，**书脊沿页高方向**。

### 请求

`POST /api/v1/impose/stock-plan`，`Content-Type: application/json`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `total_pages` | 整数 | ≥ 1 | 总页数（正整数），沿用普通拼版的分帖参数 |
| `max_sheets_per_signature` | 整数 | ≥ 1 | 每帖最多纸张数；每帖最多容纳其 **4 倍**页数 |
| `binding` | 字符串 | `left` / `right` | 装订方向：左装订 / 右装订 |
| `page_width_mm` | 数值 | 正数（有限值） | 单页宽度（mm） |
| `page_height_mm` | 数值 | 正数（有限值） | 单页高度（mm）；书脊沿页高 |
| `gutter_mm` | 数值 | 非负数（有限值） | 中缝宽度（mm），允许为 `0` |
| `copies` | 整数 | ≥ 1（严格整数） | 印数；总需求 = 每册印张数 × 印数 |
| `papers` | 对象数组 | 1～6 项 | 原纸规格列表，按输入顺序作为用量字典序与结果顺序 |
| `papers[].width_mm` | 整数 | ≥ 1（严格整数） | 原纸宽度（mm） |
| `papers[].height_mm` | 整数 | ≥ 1（严格整数） | 原纸高度（mm） |
| `papers[].inventory` | 整数 | 0～30（严格整数） | 该规格库存张数 |
| `papers[].grain` | 字符串 | `width` / `height` | 纸纹方向：`width`=纸纹沿原纸宽度，`height`=沿原纸高度 |
| `margin_mm` | 数值 | 非负数（有限值） | 原纸**四周统一留边**（mm） |
| `spacing_mm` | 数值 | 非负数（有限值） | 相邻成品印张之间的**统一裁切间隔**（mm） |

```bash
curl -X POST http://localhost:8000/api/v1/impose/stock-plan \
  -H "Content-Type: application/json" \
  -d '{
    "total_pages": 4,
    "max_sheets_per_signature": 1,
    "binding": "left",
    "page_width_mm": 210,
    "page_height_mm": 297,
    "gutter_mm": 0,
    "copies": 100,
    "papers": [
      {"width_mm": 880, "height_mm": 620, "inventory": 30, "grain": "height"},
      {"width_mm": 1000, "height_mm": 700, "inventory": 10, "grain": "height"}
    ],
    "margin_mm": 10,
    "spacing_mm": 5
  }'
```

### 排布与优选规则

- **唯一合法朝向**：成品书脊沿页高，只能按**书脊与纸纹平行**的朝向落版，不允许旋转调换：
  - `grain = "height"`（纸纹沿原纸高）：成品高沿原纸**高**、成品宽沿原纸**宽**；
  - `grain = "width"`（纸纹沿原纸宽）：成品高沿原纸**宽**、成品宽沿原纸**高**（成品整体旋转 90° 落版）。
- **可用区域**：扣除四周统一留边后为
  `(原纸宽 − 2 × margin_mm) × (原纸高 − 2 × margin_mm)`。
- **整行整列排满（十进制精确核算）**：沿某方向排布 `n` 个成品的实际占用为
  `n × 成品尺寸 + (n − 1) × spacing_mm`，只有该占用**不超过**扣除留边后的可用长度才计入 `n`
  （即 `n = ⌊(可用长度 + spacing_mm) / (成品尺寸 + spacing_mm)⌋`，恰好贴边仍可排入）。
  可用长度、成品尺寸与占用均按**十进制尺寸**精确计算，不用浮点容差吸收误差——
  例如留边 `0.000000025` 时可用宽为 `299.99999995`（300 − 2 × 0.000000025），
  对 100 mm 成品只能排 2 列（3 列需 300 mm，超出可用宽）；
  单张出数 `pieces_per_sheet = 列数 × 行数`，可用区域放不下任一成品时该规格出数为 `0`。
- **库存组合优选**：在各规格用量 `0 ≤ used ≤ inventory`、总产量满足总需求的全部组合中，依次
  1. **最小化原纸总面积**（`Σ used × 原纸宽 × 原纸高`）；
  2. 面积并列时**最小化超产**（总产量 − 总需求，即余量）；
  3. 仍并列时取**按输入顺序的用量字典序最小**（自上而下逐位比较，首位可小则小）。
  出数为 0 的规格永远不会被选用；全部规格出数之和（按库存计）仍不足总需求时无可行组合。

### 响应

顶层回显请求参数与拼版结果（`signature_count`、`sheets_per_copy`、`total_demand`、
成品尺寸 `sheet_width_mm` / `sheet_height_mm`）；`papers` 按请求顺序逐规格返回：

- `pieces_per_sheet` / `columns` / `rows`：单张出数与沿原纸宽/高方向的列数、行数；
- `usable_width_mm` / `usable_height_mm`：扣除留边后的可用区域尺寸；
- `used` / `production` / `area_mm2`：选中用量（张）、该规格总产量与耗用面积。

顶层另给出 `total_production`（总产量）、`surplus`（余量 = 总产量 − 总需求）与
`total_area_mm2`（选中组合耗用总面积，为可行组合中的最小值）。

上例（成品 420 × 297、留边 10、间隔 5）中，880 × 620 规格可用 860 × 600：
列 `⌊865/425⌋ = 2`、行 `⌊605/302⌋ = 2`，单张出 4；1000 × 700 规格可用 980 × 680：
列 `⌊985/425⌋ = 2`、行 `⌊685/302⌋ = 2`，同样单张出 4。需求 100：25 张小规格
面积 `25 × 880 × 620 = 13 640 000 mm²` 即可恰好满足，小于大规格方案。响应：

```json
{
  "total_pages": 4,
  "max_sheets_per_signature": 1,
  "binding": "left",
  "page_width_mm": 210.0,
  "page_height_mm": 297.0,
  "gutter_mm": 0.0,
  "copies": 100,
  "margin_mm": 10.0,
  "spacing_mm": 5.0,
  "signature_count": 1,
  "sheets_per_copy": 1,
  "total_demand": 100,
  "sheet_width_mm": 420.0,
  "sheet_height_mm": 297.0,
  "papers": [
    {
      "paper_index": 1,
      "width_mm": 880,
      "height_mm": 620,
      "grain": "height",
      "inventory": 30,
      "pieces_per_sheet": 4,
      "columns": 2,
      "rows": 2,
      "usable_width_mm": 860.0,
      "usable_height_mm": 600.0,
      "used": 25,
      "production": 100,
      "area_mm2": 13640000
    },
    {
      "paper_index": 2,
      "width_mm": 1000,
      "height_mm": 700,
      "grain": "height",
      "inventory": 10,
      "pieces_per_sheet": 4,
      "columns": 2,
      "rows": 2,
      "usable_width_mm": 980.0,
      "usable_height_mm": 680.0,
      "used": 0,
      "production": 0,
      "area_mm2": 0
    }
  ],
  "total_production": 100,
  "surplus": 0,
  "total_area_mm2": 13640000
}
```

### 非法参数与无可行组合（4xx）

- 分帖参数非法（`total_pages` / `max_sheets_per_signature` 小于 1、`binding` 取值非法）；
- `page_width_mm` / `page_height_mm` 非正或非有限、`gutter_mm` / `margin_mm` /
  `spacing_mm` 为负或非有限；`copies` 小于 1 或不是严格整数（布尔值、小数均拒绝）；
- `papers` 为空或超过 6 种；原纸宽高小于 1、库存超出 0～30、`grain` 不是
  `width`/`height`，或宽高/库存不是严格整数；含未定义字段、缺字段；
- **无可行组合**：各规格按库存满负荷的总产量仍小于总需求（含全部规格单张出数均为 0，
  例如原纸小于成品或留边占用过多）：返回 `422 Unprocessable Entity`，错误信息明确给出
  满负荷产能与总需求，例如
  `Value error, 库存原纸满负荷最多产出 30 张成品印张，无法满足总需求 100 张（每册 1 张 × 印数 100）`。

## 骑马订爬移补偿（POST /api/v1/impose/creep-plan）

骑马订装订时，内张纸包绕外张纸的书脊厚度会使内页图像在成品上向外（裁口侧）偏移，即**爬移**。
本接口按帖独立计算各页位的爬移补偿量：把每张纸正反面左右页位的图像向**纸面折缝中心**平移，
抵消装订后的偏移。页序、槽位与旋转规则完全沿用 `/api/v1/impose/press-layout`
（左右装订与长/短边翻转均以机台版面的实际槽位和旋转角为准）。本地访问地址
`http://localhost:8000/api/v1/impose/creep-plan`（改了 `HOST_PORT` 则对应替换端口）。

### 请求

`POST /api/v1/impose/creep-plan`，`Content-Type: application/json`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `total_pages` | 整数 | ≥ 1 | 总页数（正整数） |
| `max_sheets_per_signature` | 整数 | ≥ 1 | 每帖最多纸张数；每帖最多容纳其 **4 倍**页数 |
| `binding` | 字符串 | `left` / `right` | 装订方向：左装订 / 右装订 |
| `page_width_mm` | 数值 | 正数（有限值） | 单页宽度（mm） |
| `page_height_mm` | 数值 | 正数（有限值） | 单页高度（mm） |
| `gutter_mm` | 数值 | 非负数（有限值） | 中缝宽度（mm），允许为 `0` |
| `duplex_flip` | 字符串 | `long` / `short` | 双面翻转：`long`=长边翻转，`short`=短边翻转 |
| `thickness_mm` | 数值 | 正数（有限值） | 单张纸厚度（mm） |

```bash
curl -X POST http://localhost:8000/api/v1/impose/creep-plan \
  -H "Content-Type: application/json" \
  -d '{
    "total_pages": 8,
    "max_sheets_per_signature": 4,
    "binding": "left",
    "page_width_mm": 100,
    "page_height_mm": 200,
    "gutter_mm": 0,
    "duplex_flip": "long",
    "thickness_mm": 0.1
  }'
```

### 爬移计算规则

- **按帖独立计算**：每帖最外张（张号 1）位移为 `0`，向内第 `n` 张的爬移量为
  `creep = 2 × (n − 1) × thickness_mm`（每张纸在书脊处占两倍厚度的包绕量）；
  各帖互不影响，内层帖从自己的最外张重新计 0。
- **平移方向**：该张正反面左右页位的图像均向**纸面折缝中心**（纸面竖直中线）平移该量——
  左槽（`x = 0`）向纸面右侧移，纸面水平位移为 `+creep`；右槽（`x = 页宽 + 中缝`）
  向纸面左侧移，纸面水平位移为 `−creep`。位移方向只取决于槽位，与装订方向无关；
  左右装订仅影响各槽位上的页码（沿用机台版面页序）。
- **阅读方向稿件位移**：`artwork_shift_x_mm` 按页位旋转角换算——`0°`（正面与 `long`
  背面）与纸面位移相同；`180°`（`short` 背面）取反。
- **空白页位**：末帖补白的空白页位保留在结果中，`page` 为 `null`、两项位移均为 `0`。
- **上限校验**：爬移量按**十进制尺寸**精确核算，任一张的爬移量**达到**单页宽度
  （`creep ≥ page_width_mm`，含恰好相等）时返回 `422 Unprocessable Entity`，
  错误信息指出帖号与张号。

### 响应

顶层回显请求参数与纸面尺寸（`paper_width_mm` / `paper_height_mm`）；按帖号
`signature_index`、张号 `sheet_index`（从 1 开始，1 为最外张）逐张返回：

- `creep_mm`：本张爬移量（最外张为 `0`）；
- `front` / `back` 的 `left` / `right` 页位：`page`（页码，空白为 `null`）、
  `paper_shift_x_mm`（纸面水平位移，正=向纸面右侧、负=向纸面左侧）、
  `artwork_shift_x_mm`（阅读方向稿件水平位移）。

上例（8 页单帖 2 张、页宽 100、纸厚 0.1，内张爬移 0.2）响应：

```json
{
  "total_pages": 8,
  "max_sheets_per_signature": 4,
  "binding": "left",
  "page_width_mm": 100.0,
  "page_height_mm": 200.0,
  "gutter_mm": 0.0,
  "duplex_flip": "long",
  "thickness_mm": 0.1,
  "paper_width_mm": 200.0,
  "paper_height_mm": 200.0,
  "signature_count": 1,
  "signatures": [
    {
      "signature_index": 1,
      "sheet_count": 2,
      "page_count_padded": 8,
      "sheets": [
        {
          "sheet_index": 1,
          "creep_mm": 0.0,
          "front": {
            "left":  { "page": 8, "paper_shift_x_mm": 0.0, "artwork_shift_x_mm": 0.0 },
            "right": { "page": 1, "paper_shift_x_mm": 0.0, "artwork_shift_x_mm": 0.0 }
          },
          "back": {
            "left":  { "page": 7, "paper_shift_x_mm": 0.0, "artwork_shift_x_mm": 0.0 },
            "right": { "page": 2, "paper_shift_x_mm": 0.0, "artwork_shift_x_mm": 0.0 }
          }
        },
        {
          "sheet_index": 2,
          "creep_mm": 0.2,
          "front": {
            "left":  { "page": 6, "paper_shift_x_mm": 0.2,  "artwork_shift_x_mm": 0.2 },
            "right": { "page": 3, "paper_shift_x_mm": -0.2, "artwork_shift_x_mm": -0.2 }
          },
          "back": {
            "left":  { "page": 5, "paper_shift_x_mm": 0.2,  "artwork_shift_x_mm": 0.2 },
            "right": { "page": 4, "paper_shift_x_mm": -0.2, "artwork_shift_x_mm": -0.2 }
          }
        }
      ]
    }
  ]
}
```

同一请求若改为 `"duplex_flip": "short"`，背面保持槽位（背左 = 4、背右 = 5）且各页位
旋转 `180°`，内张背面左槽为
`{ "page": 4, "paper_shift_x_mm": 0.2, "artwork_shift_x_mm": -0.2 }`
（纸面位移不变，阅读方向稿件位移取反）。

### 非法参数与爬移超限（4xx）

- 机台版面参数的校验与 `/api/v1/impose/press-layout` 完全一致（尺寸非正数/非有限值、
  `duplex_flip` 或 `binding` 取值非法、含未定义字段、缺字段等）；
- `thickness_mm` 缺失、非正数（含 `0`、负数）或非有限值（`NaN`、`Infinity`）；
- **爬移量达到单页宽度**：任一张的爬移量 `2 × (张号 − 1) × thickness_mm` 达到或超过
  `page_width_mm`（按十进制尺寸精确判定，含恰好相等）：返回
  `422 Unprocessable Entity`，错误信息指出帖号与张号，例如
  `Value error, 第 1 帖第 4 张爬移量 0.9 mm 达到单页宽度 0.9 mm，无法完成爬移补偿`。

## 章节分帖拼版（POST /api/v1/impose/chapters）
在 `/api/v1/impose` 的基础上支持**章节感知**分帖：章节不可跨帖，相邻章节可合帖。
本地访问地址 `http://localhost:8000/api/v1/impose/chapters`（改了 `HOST_PORT` 则对应替换端口）。

### 请求

`POST /api/v1/impose/chapters`，`Content-Type: application/json`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `total_pages` | 整数 | ≥ 1 | 总页数（正整数） |
| `max_sheets_per_signature` | 整数 | ≥ 1 | 每帖最多纸张数；每帖实际页数不超过其 **4 倍** |
| `binding` | 字符串 | `left` / `right` | 装订方向：左装订 / 右装订 |
| `chapter_starts` | 整数数组 | 严格递增、首项为 1、末项 ≤ `total_pages` | 各章节首页页码 |

```bash
curl -X POST http://localhost:8000/api/v1/impose/chapters \
  -H "Content-Type: application/json" \
  -d '{"total_pages": 20, "max_sheets_per_signature": 2, "binding": "left", "chapter_starts": [1, 5, 9, 13]}'
```

### 响应

沿用 `sheets` 页位结构（与 `/api/v1/impose` 相同），并为每帖补充原页起止页码
`page_start` / `page_end` 与尾部空白数 `blank_count`：

```json
{
  "total_pages": 20,
  "max_sheets_per_signature": 2,
  "binding": "left",
  "chapter_starts": [1, 5, 9, 13],
  "signature_count": 3,
  "signatures": [
    {
      "signature_index": 1,
      "sheet_count": 1,
      "page_count_padded": 4,
      "page_start": 1,
      "page_end": 4,
      "blank_count": 0,
      "sheets": [
        {
          "sheet_index": 1,
          "front": { "left": 4, "right": 1 },
          "back":  { "left": 2, "right": 3 }
        }
      ]
    }
  ]
}
```

> 上例仅展示第 1 帖；实际响应含全部 3 帖（原页范围 1–4、5–12、13–20）。

### 分帖规则

1. 章节不可跨帖，相邻章节可合帖；每帖实际页数不超过 `4 × max_sheets_per_signature`，
   单章超过该上限时返回 `422 Unprocessable Entity`。
2. 在满足容量约束的分帖方案中，依次最小化：各帖补至 4 的倍数所需**空白页总数** →
   **帖数**；仍相同则优先**最早的分帖边界**。
3. 每帖各自在**尾部**补空白至 4 的倍数（`null`），再按与 `/api/v1/impose`
   相同的正反面拼版规则排列。

### 非法参数（4xx）

除与 `/api/v1/impose` 相同的校验外，`chapter_starts` 为空、首项不为 1、未严格递增、
超过 `total_pages`，或某一单章页数超过 `4 × max_sheets_per_signature` 时，
均返回 `422 Unprocessable Entity`。

## 重印复用（POST /api/v1/impose/reprint）

旧版加印时，若新版的某张印张与旧版某张**完全一致且页内内容均未改动**，可直接复用旧印张、
无需重印；其余印张整张重印。本地访问地址
`http://localhost:8000/api/v1/impose/reprint`（改了 `HOST_PORT` 则对应替换端口）。

两版分别沿用普通拼版（`/api/v1/impose`）的分帖、末帖尾部补空白与左右页位规则，
使用两版共用的 `max_sheets_per_signature` 与 `binding`。

### 请求

`POST /api/v1/impose/reprint`，`Content-Type: application/json`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `old_page_ids` | 字符串数组 | 非空数组；元素为非空字符串、**版内不重复** | 旧版页面 ID，按阅读顺序排列 |
| `new_page_ids` | 字符串数组 | 非空数组；元素为非空字符串、**版内不重复** | 新版页面 ID，按阅读顺序排列 |
| `max_sheets_per_signature` | 整数 | ≥ 1 | 两版共用的每帖最多纸张数 |
| `binding` | 字符串 | `left` / `right` | 两版共用的装订方向 |
| `changed_page_ids` | 字符串数组 | 每个 ID 必须属于新版；允许重复、允许为空 | 新版内容改动的页面 ID |

```bash
curl -X POST http://localhost:8000/api/v1/impose/reprint \
  -H "Content-Type: application/json" \
  -d '{
    "old_page_ids": ["p1","p2","p3","p4","p5","p6","p7","p8"],
    "new_page_ids": ["p1","p2","p3","p4","p5","p6X","p7","p8"],
    "max_sheets_per_signature": 2,
    "binding": "left",
    "changed_page_ids": ["p6X"]
  }'
```

### 复用规则

新版每张印张按下列规则判定（四个页位指 `front.left` / `front.right` /
`back.left` / `back.right`，空白页位为 `null`）：

1. 四个页位与某张**旧版印张完全相同**（页位一一对应，ID 相同、空白位置也相同），
   **允许跨帖**匹配；
2. 四个页位中的非空页面 ID **均不在** `changed_page_ids` 中；
3. 每张旧版印张**最多被复用一次**（含页位全为空白的印张，按旧版帖号、张号顺序取用）。

以上任一不满足即**整张重印**。例如改动只涉及一张纸上的其中一页，该纸四个页位所在整面
仍需整张重印，但不影响其他印张复用。

### 响应

按**新版帖号、张号**逐张返回：

- `front` / `back` 的左、右页位：新版页面 ID 或 `null`（空白）；
- `reused`：是否复用旧版印张，`false` 表示整张重印；
- `old_signature_index` / `old_sheet_index`：复用时给出旧帖号与旧帖内张号
  （均从 1 开始，张号 1 为最外张）；重印时均为 `null`；
- 顶层 `reprint_sheet_count`：整张重印的总张数。

```json
{
  "old_page_ids": ["p1","p2","p3","p4","p5","p6","p7","p8"],
  "new_page_ids": ["p1","p2","p3","p4","p5","p6X","p7","p8"],
  "changed_page_ids": ["p6X"],
  "max_sheets_per_signature": 2,
  "binding": "left",
  "signature_count": 1,
  "reprint_sheet_count": 1,
  "signatures": [
    {
      "signature_index": 1,
      "sheet_count": 2,
      "page_count_padded": 8,
      "sheets": [
        {
          "sheet_index": 1,
          "front": { "left": "p8", "right": "p1" },
          "back": { "left": "p2", "right": "p7" },
          "reused": true,
          "old_signature_index": 1,
          "old_sheet_index": 1
        },
        {
          "sheet_index": 2,
          "front": { "left": "p6X", "right": "p3" },
          "back": { "left": "p4", "right": "p5" },
          "reused": false,
          "old_signature_index": null,
          "old_sheet_index": null
        }
      ]
    }
  ]
}
```

### 非法参数（4xx）

除与 `/api/v1/impose` 相同的校验（`max_sheets_per_signature`、`binding`、未定义字段等）外，
任一版页面 ID 列表为空、包含空字符串、版内 ID 重复，或 `changed_page_ids` 包含空字符串、
含有不属于新版的页面 ID 时，均返回 `422 Unprocessable Entity`。

## 印张抽检（POST /api/v1/impose/inspect）

车间实拍/人工读回的**实物印张是乱序的**，且每张纸拿起时的朝向不固定。本接口先沿用
`/api/v1/impose` 的拼版规则（含末帖尾部补空白与左/右装订镜像）由页面 ID 生成**预期印张**，
再把每张实物观测与预期印张配对核对。本地访问地址
`http://localhost:8000/api/v1/impose/inspect`（改了 `HOST_PORT` 则对应替换端口）。

### 请求

`POST /api/v1/impose/inspect`，`Content-Type: application/json`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `page_ids` | 字符串数组 | 非空；非空字符串、**互不重复**，且不能为 `"?"` | 页面 ID，按**阅读顺序**排列 |
| `max_sheets_per_signature` | 整数 | ≥ 1 | 每帖最多纸张数；每帖最多容纳其 4 倍页数 |
| `binding` | 字符串 | `left` / `right` | 装订方向：左装订 / 右装订 |
| `observed_sheets` | 对象数组 | 非空 | 乱序的实物印张；每张含 `front`/`back`，其 `left`/`right` 页位为页面 ID、`null`（空白）或 `"?"`（未读出） |

页位三态含义：

- 页面 ID（非空字符串，不能是 `"?"`）：该页位读出的页面；ID 不要求出现在 `page_ids`
  中——读到外来 ID 时仍可配对，但该页位计为错误；
- `null`：明确读到的**空白页位**（是已知信息，与预期 `null` 吻合算对，与预期页面 ID 不符算错）；
- `"?"`：该页位**未读出**（不计错、不参与吻合数，也不能作为配对线索）。

```bash
curl -X POST http://localhost:8000/api/v1/impose/inspect \
  -H "Content-Type: application/json" \
  -d '{
    "page_ids": ["p1","p2","p3","p4","p5","p6","p7","p8","p9","p10","p11","p12"],
    "max_sheets_per_signature": 2,
    "binding": "left",
    "observed_sheets": [
      {"front": {"left": "p8", "right": "p1"}, "back": {"left": "p2", "right": "?"}},
      {"front": {"left": "p4", "right": "p5"}, "back": {"left": "p6", "right": "pX"}},
      {"front": {"left": "?",  "right": "?"},  "back": {"left": "z9", "right": "?"}}
    ]
  }'
```

### 配对与裁决规则

每张观测可按以下 **4 种变换**之一解释（`none` 原样、`mirror_lr` 左右镜像、
`flip_fb` 正反互换、`mirror_lr_flip_fb` 两者组合）：

1. **配对门槛**：观测至少有一个非空、已读（非 `"?"`）的页面 ID 出现在该张预期印张的
   四个页位中，才允许与该张配对；全为 `null`/`"?"`、或只有外来 ID 的观测无法配对。
2. 在**每张预期印张、每张观测至多使用一次**的前提下，依次优化：
   1. **最大化配对数**；
   2. 再最大化全部配对的**已读页位吻合数**（页面 ID 相同或 `null` 对 `null` 算吻合，
      `"?"` 不计入）；
   3. 仍同分则按 **观测序号升序 → 预期帖号/张号升序 → 变换顺序
      （`none`、`mirror_lr`、`flip_fb`、`mirror_lr_flip_fb`）** 裁决。
3. 同一观测与某张预期印张之间，取吻合数最多的变换；吻合数相同取变换顺序最前者。
   `"?"` 不计错；其余已知页位（含 `null`）与按选定变换解释后的预期不符时，逐条列入
   `errors`。

### 响应

`observations` 按请求中的观测顺序逐张返回：

- `matched`：是否配对成功；成功时给出 `signature_index` / `sheet_index`（均从 1 开始，
  张号 1 为最外张）与 `transform`；失败时这三项为 `null`；
- `matched_slot_count`：已读页位吻合数（`"?"` 不计入）；
- `errors`：已知页位错误明细，每项含 `position`
  （`front_left` / `front_right` / `back_left` / `back_right`，按观测**原样朝向**）、
  `observed`（读到的 ID 或 `null`）、`expected`（按选定变换解释后的预期 ID 或 `null`）；
- 顶层另给出 `unmatched_observations`（无法配对的观测，按观测序号排列）与
  `unseen_signatures`（未见的预期印张，按帖号/张号排列）及三者的计数。

上例中：观测 1 原样对应第 1 帖最外张（1 个 `"?"`，吻合 3 个页位）；
观测 2 按正反互换对应第 1 帖内张，唯读错的 `back_right` 应为 `p3`；
观测 3 只有外来 ID `z9` 无法配对；第 2 帖印张未见。

```json
{
  "page_ids": ["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8", "p9", "p10", "p11", "p12"],
  "max_sheets_per_signature": 2,
  "binding": "left",
  "matched_observation_count": 2,
  "unmatched_observation_count": 1,
  "unseen_sheet_count": 1,
  "observations": [
    {
      "observation_index": 1,
      "front": { "left": "p8", "right": "p1" },
      "back": { "left": "p2", "right": "?" },
      "matched": true,
      "signature_index": 1,
      "sheet_index": 1,
      "transform": "none",
      "matched_slot_count": 3,
      "errors": []
    },
    {
      "observation_index": 2,
      "front": { "left": "p4", "right": "p5" },
      "back": { "left": "p6", "right": "pX" },
      "matched": true,
      "signature_index": 1,
      "sheet_index": 2,
      "transform": "flip_fb",
      "matched_slot_count": 3,
      "errors": [
        { "position": "back_right", "observed": "pX", "expected": "p3" }
      ]
    },
    {
      "observation_index": 3,
      "front": { "left": "?", "right": "?" },
      "back": { "left": "z9", "right": "?" },
      "matched": false,
      "signature_index": null,
      "sheet_index": null,
      "transform": null,
      "matched_slot_count": 0,
      "errors": []
    }
  ],
  "unmatched_observations": [
    {
      "observation_index": 3,
      "front": { "left": "?", "right": "?" },
      "back": { "left": "z9", "right": "?" }
    }
  ],
  "unseen_signatures": [
    {
      "signature_index": 2,
      "sheet_index": 1,
      "front": { "left": "p12", "right": "p9" },
      "back": { "left": "p10", "right": "p11" }
    }
  ]
}
```

### 非法参数（4xx）

除与 `/api/v1/impose` 相同的校验（`max_sheets_per_signature`、`binding`、未定义字段等）外，
`page_ids` 或 `observed_sheets` 为空、页面 ID 为空字符串/重复/为 `"?"`，
或实物页位为空字符串时，均返回 `422 Unprocessable Entity`。
（页位缺字段或类型错误同样返回 422；空白页须显式传 `null`，未读出传 `"?"`。）

## 本地开发（不使用 Docker）

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
pytest -q
```

## 项目结构

```
.
├── app/
│   ├── __init__.py
│   ├── press_geometry.py # 页位几何：装订/翻转决定的实际槽位页码、槽位原点与 0°/180° 双向坐标变换（press-layout / locate-defects / ink-zones / trim-safety 共用）
│   ├── imposition.py   # 拼版核心算法（分帖 + 帖内拼版 + 机台版面 + 瑕疵定位 + 墨区着墨面积 + 外裁/折缝安全检查 + 订针计划 + 原纸备料 + 骑马订爬移补偿）
│   ├── proof.py        # 双面拼版校样 PDF 生成（沿用机台版面结果）
│   ├── fonts/          # 校样 PDF 嵌入的子集化中文字体
│   └── main.py         # FastAPI 路由与参数校验
├── tests/              # 算法与 API 测试（pytest）
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt
└── README.md
```
