# 经营看板 + 问答服务
# 换数据或知识库：make rebuild DATA_DIR=/path/data KB_DIR=/path/kb
# 模型三件套写在仓库根的 .env 里即可（自动读取）；mock 模式用 make run-mock。

# Windows 下虚拟环境的解释器在 Scripts/，其余平台在 bin/。
ifeq ($(OS),Windows_NT)
PY ?= .venv/Scripts/python
else
PY ?= .venv/bin/python
endif
PORT ?= 8000
export DATA_DIR KB_DIR VAR_DIR LLM_BASE_URL LLM_API_KEY LLM_MODEL ENV_FILE

.PHONY: setup rebuild run run-mock test clean

setup:          ## 建虚拟环境并装依赖
	python -m venv .venv
	$(PY) -m pip install -r requirements.txt

rebuild:        ## 从 DATA_DIR 与 KB_DIR 重建清洗表和检索索引
	$(PY) -m kbqa.rebuild

run:            ## 启动服务，默认 8000 端口（有 .env 走 live，否则 mock）
	$(PY) -m uvicorn kbqa.server:app --host 127.0.0.1 --port $(PORT)

run-mock:       ## 强制 mock 启动：不读 .env，不请求任何付费模型
	ENV_FILE= $(PY) -m uvicorn kbqa.server:app --host 127.0.0.1 --port $(PORT)

test:           ## 跑测试
	$(PY) -m pytest tests -q

clean:          ## 删掉清洗表
	rm -rf var
