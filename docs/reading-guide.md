# 怎么看懂整个仓库

先记住这个公式：**用户意图 → 检查输入 → 固定执行方案 → 调用成熟引擎 → 检查结果 → 人工判断**。

不要一开始逐行看完所有文件。沿着一次命令的调用链读，每个模块只问三个问题：它接收什么、检查什么、交给谁。

| 顺序 | 文件 | 先看这些函数 | 核心问题 |
| --- | --- | --- | --- |
| 1 | `src/fmri_prep_flow/cli.py` | `build_parser()`、`main()`、`_prepare()` | 用户命令怎样变成函数调用？ |
| 2 | `config.py`、`fmri-prep-flow init` 生成的配置 | `load_config()` | 哪些参数有默认值，哪些选择必须明确？ |
| 3 | `models.py` | `identity()`、`run_id()` | 如何区分采集？为什么 echo 不等于一个 run？ |
| 4 | `inputs/bids.py` | `discover()`，再回头看辅助函数 | BIDS 文件、继承元数据和场图如何组成 manifest？ |
| 5 | `inputs/audit.py` | `inspect_image()`、`check_bold_metadata()`、`check_echoes()` | 文件能读和采集信息一致是两种检查。 |
| 6 | `inputs/prepare.py`、`inputs/validation.py` | `prepare()`、`validate()` | 为什么复制原始数据？官方 BIDS 验证在哪？ |
| 7 | `pipeline/policy.py`、`pipeline/runtime.py` | `resolve_policies()`、`command()` | 科学策略怎样变成 Singularity/fMRIPrep 参数？ |
| 8 | `pipeline/planning.py` | `create_plan()`、`verify_plan()` | 为什么先计划后执行？哈希防止什么变化？ |
| 9 | `pipeline/runner.py`、`pipeline/executor.py` | `run()`、`execute()` | 谁记录状态，谁等待进程，谁处理中断？ |
| 10 | `outputs/products.py` | `check_run()`、`evidence()` | 容器返回 0 后，还要检查哪些东西？ |
| 11 | `outputs/qc.py`、`outputs/review.py`、`outputs/catalog.py` | `preview()`、`submit()`、`collect()` | 图、人工结论和结果表为什么分开？ |

## 用 prepare 练习一次

```text
fmri-prep-flow prepare --selection selection.json --output prepared
        │
        ▼
cli.build_parser() 注册 prepare 参数与 _prepare
        │
cli.main() 解析参数；args.func(args) 调用 _prepare
        │
inputs.prepare.prepare()
        ├── bids.discover() → 选择、继承、关联、审计
        ├── 复制到 prepared/bids/，写入有效 JSON
        ├── manifest.json → 来源与采集信息
        ├── staging.json → 副本清单及哈希
        └── validation.validate() → 官方验证报告
```

`p.set_defaults(func=_prepare)` 只是把函数对象放进解析结果。它没有当场调用 `_prepare`。最后的 `args.func(args)` 才真正执行业务逻辑。

套路可以复用到别的工具：

```python
p = commands.add_parser("命令名", help="做什么")
p.add_argument("--输入", required=True)
p.set_defaults(func=处理函数)

args = parser.parse_args()
result = args.func(args)
```

这里不需要类继承、注册框架或插件系统。一个命令调用一个业务入口，业务入口再按顺序调用职责单一的函数。
