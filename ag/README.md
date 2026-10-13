# Auto-Gaussian CLI
此目录是独立的 `ag` 项目；安装：`pip install -e "ag[test,chem]"`，查看版本：`ag --version`。
命令、模板与文件格式见[改造方案第 4 节](../docs/REDESIGN-PLAN.md#4-ag-规格)；子命令模块通过 `register(subparsers)` 注册，并用 `set_defaults(func=handler)` 指定处理函数。
