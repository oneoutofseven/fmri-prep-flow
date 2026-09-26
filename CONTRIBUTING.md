# 开发

在 Linux 和 Python ≥ 3.10 环境中安装：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
ruff check src tests
ruff format --check src tests
pytest -q
python -m build
```

单元测试使用临时生成的合成影像和替代 validator / container，不需要下载真实 MRI、Singularity 或 FreeSurfer license。实际输入验证需要另外安装 `.[validator]`；真实预处理需要完整运行环境。

代码沿着 `cli → inputs → pipeline → outputs` 组织。CLI 负责参数解析，业务函数负责处理；不在公共模块里增加与某个数据集绑定的路径或规则。默认配置只在 `config.py` 维护。

修改输入规则、处理策略或产物契约时，增加相应的行为测试，并同步 protocol。科学策略的变化需要代表性数据验证；单元测试和容器返回码不能代替图像 QC。报告问题时提供工具版本、最小配置、错误和复现步骤，不提交 license、可识别个体信息或整个工作目录。

GitHub Actions 配置测试 Python 3.10、3.12、3.13，并从源码构建 sdist/wheel，在仓库外检查安装后的 CLI。它不会自动启动完整 fMRIPrep 作业。
