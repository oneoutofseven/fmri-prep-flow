# fMRI 预处理 protocol

## 1. 适用范围和准备

使用原始 BIDS 的 T1w 与固定 TR BOLD；优先成人、体积分析。支持单/多回波、有/无 session、多个被试和采集身份。当前不覆盖 variable TR、表面/CIFTI、任务 GLM、自动生理回归、tedana ICA 或任意裸 NIfTI 转 BIDS。
同一被试多个 session 使用 sessionwise 解剖参考；每个选定 session 必须有原始 T1w。没有 T1w 的 session 不自动借用另一访视。
输出固定 `T1w` 和 `MNI152NLin2009cAsym:res-2`，资源默认 8 CPU、8 OMP、32000 MB。原始 shape 可以不同；检查依据各自 NIfTI 网格，标准空间输出再检查 2 mm 体素。配准正确性仍需人工查看。

## 2. prepare：建立可追溯的输入

1. 在 selection 中明确 subjects，可筛选 sessions/tasks/runs/acquisitions/directions。未指定的字段不过滤，过滤组合内的所有匹配都会进入计划。
2. PyBIDS 查询和解析继承 JSON；同级无明确优先级且字段矛盾时拒绝。完整保留参与继承的 JSON 路径与哈希。
3. 按采集身份分组，多回波仅排除 echo 实体。echo 从 1 连续，TE 递增，TR、时间长度、空间网格、切片时间一致。单个带 echo 标签的图像视为不完整采集。
4. 审计压缩完整性、有限值、非恒定 BOLD、空间单位和 qform/sform；逐项检查 JSON TR、NIfTI TR、TE、已有的方向和切片时间。切片方向缺失时按固定引擎的 k 轴约定检查长度，不向原始 JSON 补写该字段。
5. 按 B0FieldSource/B0FieldIdentifier 或 IntendedFor 关联场图，包括 magnitude/phase 配套文件；支持同数据集 `bids::` 引用。SBRef/events/physio 按兼容实体关联并保留。
6. 独立复制 NIfTI/关联文件；有效元数据写成逐文件 sidecar；删除副本中指向未入选文件的 IntendedFor 条目，原始数据不变。
7. 官方 BIDS Validator 必须通过。保留完整 warnings，它们不等于自动排除，也不等于元数据物理正确。

`manifest.json` 保存原始来源；`staging.json` 保存副本；后续执行依赖副本的完整文件集及哈希。源数据不需保持挂载，但必须保留溯源记录。输入错误会保留已有诊断文件，修复来源后使用新输出目录。

## 3. plan：决定校正策略并冻结

| 配置 | 行为 |
| --- | --- |
| `sdc=auto` | 必须找到完整、受支持的场图及必要元数据；无场图则阻止计划。 |
| `sdc=syn` | 显式基于解剖校正；必须有 PED/TRT；映射为 `--ignore fieldmaps --use-syn-sdc error --force syn-sdc`。 |
| `sdc=none` | 显式 `--ignore fieldmaps`；必须填写 `sdc_reason`。 |
| `slice_timing=auto` | 有合法 SliceTiming 时交给引擎；缺失时记录预期跳过。 |
| `slice_timing=require` | 缺失时拒绝；完成后报告必须确认 Applied。 |
| `slice_timing=skip` | 显式 `--ignore slicetiming`；已有非法元数据仍不忽略。 |
| `me_output_echos=true` | 多回波额外保留原生空间预处理 echo；不要求每个 echo 都有 MNI 输出。 |

auto 支持 EPI 反向编码、phasediff+magnitude1、fieldmap+magnitude。phase1/phase2、跨数据集场图引用及复杂/不完整场图组合会明确拒绝。关联和元数据检查不取代实际场图采集验证。

固定 fMRIPrep 25.2.5 镜像摘要。计划冻结输入副本、manifest、官方验证、配置、源码清单和每个被试的命令。实际执行前逐项核对；发生变化需要新计划。fs_license 可在配置中设置，也可来自 FS_LICENSE；计划创建时解析并固定路径，不记录 license 内容。

## 4. run：执行和验收

Singularity 挂载输入为只读，工作和结果目录可写。按被试顺序执行，每个被试包含其所有选定采集；失败停止后续被试，已完成被试保留自己的状态。锁避免同一计划重复运行；中断会结束容器进程组。

固定参数包含 sessionwise、无表面重建、强制颅骨剥离、固定随机种子。详细参数以生成的 commands.sh 和 plan.json 为准。`--cleanenv` 隔离容器环境。可通过 `SINGULARITY_CACHEDIR` / `SINGULARITY_TMPDIR` 选择现有缓存或临时盘；默认放在任务目录。TemplateFlow 首次需要联网下载。若主机已有缓存，可设置 `TEMPLATEFLOW_HOME`，启动时会复制到新的任务目录并记录清单，不改写原缓存。

返回码 0 之后，逐 run 检查：

- 两个空间的组合 BOLD、boldref、binary mask：帧数、有限值、网格、TR 和 MNI 2 mm 体素。
- confounds TSV/JSON：行数与帧数一致，基础头动字段有效；首帧 FD/DVARS 允许未定义，统计不补成零。
- 要求保留时的每个 echo、BOLD→T1 和 T1→MNI 变换、HTML 报告。
- 从功能摘要读取实际 SDC/STC；SyN/场图策略必须得到相应方法证据及 SDC 图，不能只凭命令标记成功。

当前检查不对所有衍生产物做穷举验证，也不证明配准精度。输入/输出哈希可检测意外变化，不是防恶意篡改的签名机制。

产物验收成功记为 completed。QC PNG 生成错误单独记录，不能把已成功的 MRI 处理改成 failed。可用独立 qc 命令输出到新目录重试。

## 5. 人工 QC

使用 review --template 生成表单，打开被试 HTML 与各 run QC 图，逐项填写：

| 字段 | 主要查看 |
| --- | --- |
| brain_extraction | T1 脑提取边界、组织分割，是否丢脑/含明显颅外组织 |
| bold_to_t1 | BOLD 与 T1 脑轮廓、脑室、皮层位置是否对齐 |
| standard_alignment | T1/BOLD 对标准空间的整体和局部配准 |
| distortion | 实际校正方法、前后图、额颞叶残余畸变；none 时记录对用途的影响 |
| signal_dropout | 覆盖范围、信号丢失、重影、明显伪影 |
| motion_and_timeseries | FD、DVARS、carpet、非稳态帧；按研究方案判断可用时长 |

每项 pass/fail，decision 与各项一致，填写真实人工 reviewer 和 notes；所有 run 均须覆盖。AI 观察可另存文字，不填写正式人工身份。头动参考线 0.5 mm 只是描述性辅助，不自动变为排除标准。

collect 导出所有 run/空间，包含 requested_sdc、actual_sdc、processing 和 human_qc。pending/fail 仍保留在表内，由后续研究流程显式选择，工具不默认纳入。

## 6. 后续分析边界

本工具到空间预处理、confounds、QC 和结果索引为止。不会删除初始非稳态帧、进行 nuisance 回归、滤波、平滑、GSR、tedana ICA 或计算功能连接。后续分析需根据研究方案处理非稳态与高头动帧，并明确回归项、滤波和 censoring 策略。多回波最优组合不能等同于 ICA 去噪。

## 参考

- [fMRIPrep 25.2.5 CLI](https://fmriprep.org/en/25.2.5/usage.html)：容器参数与解剖参考策略。
- [fMRIPrep outputs](https://fmriprep.org/en/25.2.5/outputs.html)：confounds、echo 和衍生结果约定。
- [BIDS MRI 规范](https://bids-specification.readthedocs.io/en/v1.11.0/modality-specific-files/magnetic-resonance-imaging-data.html)：采集元数据与场图关联。
- [PyBIDS](https://bids-standard.github.io/pybids/examples/pybids_tutorial.html)：实体查询及元数据继承。
