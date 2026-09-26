# 配置说明

运行 `fmri-prep-flow init --output project` 生成完整默认配置。默认值只在 `src/fmri_prep_flow/config.py` 中维护，不需要手工复制另一份模板。配置文件允许只填写覆盖项；未知字段会报错。

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `nprocs` | `8` | fMRIPrep 进程预算，正整数 |
| `omp_nthreads` | `8` | 单个 OpenMP 任务线程数，不超过 `nprocs` |
| `mem_mb` | `32000` | 内存调度预算，单位 MB，非系统硬限制 |
| `output_spaces` | `["T1w", "MNI152NLin2009cAsym:res-2"]` | 当前固定支持这两个输出空间 |
| `fs_license` | `null` | 未设置时读取 `FS_LICENSE`；相对路径以配置文件目录为基准 |
| `sdc` | `"auto"` | `auto`、`syn` 或 `none` |
| `sdc_reason` | `""` | `sdc=none` 时必须说明理由 |
| `slice_timing` | `"auto"` | `auto`：根据元数据决定；`require`：必须执行；`skip`：明确跳过 |
| `me_output_echos` | `true` | 多回波额外保留各 echo 的原生空间预处理结果 |

`auto` 不会悄悄降级为无畸变矫正。当前接受 EPI 反向编码、phasediff+magnitude1、fieldmap+magnitude；具体要求见 [protocol](protocol.md)。`syn` 显式忽略场图并请求基于解剖的校正，本工具要求 BOLD sidecar 中有真实的 `PhaseEncodingDirection` 和 `TotalReadoutTime`。

如果研究方案明确选择无 SDC，可用这样的配置覆盖项：

```json
{
  "sdc": "none",
  "sdc_reason": "Study protocol specifies an uncorrected pilot; residual distortion will be reviewed.",
  "nprocs": 8,
  "omp_nthreads": 4,
  "mem_mb": 32000
}
```

示例理由需换成自己研究的实际依据；它不是通用推荐配置。

## 环境和缓存

- `FS_LICENSE`：个人 FreeSurfer license 文件路径。
- `SINGULARITY_CACHEDIR` / `SINGULARITY_TMPDIR`：可选共享镜像缓存和临时目录；否则每个任务创建独立目录。
- `TEMPLATEFLOW_HOME`：可选已有模板缓存。工具将其复制到新任务目录并记录清单，不修改源缓存。

```bash
export FS_LICENSE=/absolute/path/to/license.txt
export SINGULARITY_CACHEDIR=/scratch/my-user/singularity-cache
export SINGULARITY_TMPDIR=/scratch/my-user/singularity-tmp
```

镜像版本、解剖参考方式、输出空间和随机种子是受支持 protocol 的一部分，不提供任意额外容器参数入口。改变这些行为应修改代码、补充检查并创建新计划。

## 计划与目录

输入、输出目录不能重叠。`init`、`prepare` 和 `plan` 需要新目录。计划绑定当前输入、配置、Python 环境、源码和绝对路径；修改文件、升级安装或移动目录后需重新生成计划。已有运行结果可保留用于复核，但不能用新安装继续执行旧计划。
