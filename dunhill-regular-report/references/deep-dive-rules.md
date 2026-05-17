# Deep Dive Rules

## Trigger
After Auto Scan completes, present Findings Checklist and ask:
"以上是自动扫描发现。你想深挖哪些点？可以选编号，也可以直接说你关注的方向。"

## Interaction Modes

### Mode 1: From Findings
User selects finding numbers (e.g., "1, 3, 5"). AI performs targeted analysis on those items.

### Mode 2: Free-form Question
User asks directly (e.g., "为什么 Footwear 折扣加深了"). AI locates relevant data and analyzes.

### Mode 3: Follow-up Chain
After AI presents analysis, user can drill deeper:
- "那 Belts 品类呢？" → same analysis for different segment
- "和上月比呢？" → same analysis for different period
- "具体是哪几天？" → time granularity drill-down

### Mode 4: Dimension Switch
User can change direction anytime: "换个方向，看看客户分析"

## AI Behavior Rules

### Analysis Structure (for each deep dive)
1. **Data facts first** — present numbers, tables, trends
2. **Possible causes** — hypotheses based on data patterns
3. **Recommendations** — actionable suggestions
4. **Confidence level** — explicitly state how confident

### Hard Rules (硬性规则)

#### Rule 1: Data-Driven, No Fabrication
- All conclusions MUST trace back to specific data cells
- If data cannot confirm a claim, mark as [待确认]
- Never invent numbers, trends, or patterns

#### Rule 2: When Uncertain, Ask
- Data contradiction → stop and ask user
- Unclear measurement caliber → stop and ask user
- Insufficient sample size → note and ask if user wants to proceed
- Never guess when uncertain

#### Rule 3: Separate Facts from Inferences
- "数据显示..." = fact (confirmed by data)
- "可能原因是..." = inference (hypothesis)
- Every inference must carry confidence level:
  - [高置信] — multiple data points support
  - [中置信] — some data support, alternative explanations exist
  - [低置信] — limited data, needs user validation
  - [待确认] — cannot determine from available data

#### Rule 4: Metric Priority
All deep dives follow: NET > GMV > RRC > CVR > ATV > AUR > UPT

### Exit Signal
User says any of: "差不多了", "可以出报告了", "出报告", "够了", or similar → proceed to Report Generation phase.

## Example Interaction

User: "1, 3"
AI: (Analyzes finding #1 and #3 in depth, each with data → causes → recommendations)

User: "退款率上升具体是哪些品类？"
AI: (Drills into refund data by category, presents breakdown table)

User: "Footwear的退款原因是什么？"
AI: (Further drills into Footwear refund reasons, presents distribution)

User: "可以出报告了"
AI: (Proceeds to Phase 4: Report Generation)