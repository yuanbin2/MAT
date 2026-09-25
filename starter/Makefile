# 经营看板 + 问答服务
# 换数据或知识库：make rebuild DATA_DIR=/path/data KB_DIR=/path/kb
# 模型三件套写在仓库根的 .env 里即可（服务会自动读取）；要强制走本地降级用 make run-mock。

# Windows 下虚拟环境的解释器在 Scripts/，其余平台在 bin/。
ifeq ($(OS),Windows_NT)
PY ?= .venv/Scripts/python
else
PY ?= .venv/bin/python
endif
PORT ?= 8000

# 这三个路径变量为空也无害：代码里空值会回退到默认目录。
export DATA_DIR KB_DIR VAR_DIR

# 只有"外部真的设过"（环境变量或命令行）的变量才导出。
#
# 为什么不能直接写 `export ENV_FILE LLM_BASE_URL LLM_API_KEY LLM_MODEL`：
# Make 会把**未定义**的变量导出成空串，而空串在这里是有语义的——
#   * ENV_FILE= 空 表示"一个 .env 都不读"，于是配了 .env 也永远是 mock；
#   * LLM_API_KEY= 空 会盖掉 .env 里的值，等于把配置抹平。
# 实测：`export ENV_FILE` 且系统未设 ENV_FILE 时，子进程看到 ENV_FILE=''，
# 仓库根 .env 有 4 行有效配置仍然 llm_mode=mock。
ifneq ($(filter environment command line,$(origin ENV_FILE)),)
export ENV_FILE
endif
ifneq ($(filter environment command line,$(origin LLM_BASE_URL)),)
export LLM_BASE_URL
endif
ifneq ($(filter environment command line,$(origin LLM_API_KEY)),)
export LLM_API_KEY
endif
ifneq ($(filter environment command line,$(origin LLM_MODEL)),)
export LLM_MODEL
endif

.PHONY: setup rebuild run run-mock env-mode env-mode-mock test clean

setup:          ## 建虚拟环境并装依赖
	python -m venv .venv
	$(PY) -m pip install -r requirements.txt

rebuild:        ## 从 DATA_DIR 与 KB_DIR 重建清洗表与检索索引
	$(PY) -m kbqa.rebuild

run:            ## 启动服务，默认 8000 端口（有 .env 走 live，否则 mock）
	$(PY) -m uvicorn kbqa.server:app --host 127.0.0.1 --port $(PORT)

# 目标级 export：把这四个变量对本目标显式置空（覆盖系统里已有的三件套）。
# 这样即使机器上已经设了 LLM_*、仓库根也有 .env，run-mock 也确实是 mock。
run-mock: export ENV_FILE :=
run-mock: export LLM_BASE_URL :=
run-mock: export LLM_API_KEY :=
run-mock: export LLM_MODEL :=
run-mock:       ## 强制 mock：不读 .env，也不认系统里的三件套
	$(PY) -m uvicorn kbqa.server:app --host 127.0.0.1 --port $(PORT)

env-mode:       ## 打印当前配置推导出的模型模式（排查"配了 Key 为什么还是 mock"）
	$(PY) -m kbqa.envcheck

env-mode-mock: export ENV_FILE :=
env-mode-mock: export LLM_BASE_URL :=
env-mode-mock: export LLM_API_KEY :=
env-mode-mock: export LLM_MODEL :=
env-mode-mock: env-mode

test:           ## 跑测试
	$(PY) -m pytest tests -q

clean:          ## 删掉清洗表
	rm -rf var
