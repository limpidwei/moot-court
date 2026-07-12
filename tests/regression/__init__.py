"""
全局回归测试套件

覆盖项目关键路径，确保后续改动不会破坏已有功能：
- 证据约束模块（test_evidence_constraint.py）
- 庭审流程关键路径（test_trial_flow.py）
- Insight / 可视化（test_insights.py）

运行方式：
    cd /c/Users/86186/moot-court
    py -m pytest tests/regression/ -v

原则：
1. 每个测试都应该是独立的，不依赖其他测试的执行顺序
2. Mock LLM 调用以降低成本和提高速度
3. 断言要具体，不能放过"看起来大概对"的情况
4. 新增功能时同步补充对应的回归测试
"""
