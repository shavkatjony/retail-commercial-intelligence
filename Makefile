# Retail Commercial Intelligence & Decision System
# One-command reproducibility. `make all` rebuilds every artifact from scratch.
#
# Uses whatever `python` is on PATH — run it inside the environment where you
# installed requirements.txt (e.g. `conda activate base`). Override if needed:
#   make all PY=/opt/anaconda3/bin/python
PY ?= python

.PHONY: help all data build html notebooks clean

help:
	@echo "make all        generate sample if needed, then full build"
	@echo "make data       (re)generate the synthetic M5 sample"
	@echo "make build      ingest -> SQL -> validate -> metrics -> extracts -> HTML + hero figure"
	@echo "make html       refresh only the HTML dashboard's data (needs a prior build)"
	@echo "make notebooks  re-execute the 3 analysis notebooks against the current build"
	@echo "make clean      remove processed data and Tableau extracts"
	@echo ""
	@echo "Real data: put the Kaggle M5 CSVs in data/raw/, set mode: real in config.yaml,"
	@echo "           then:  make all && make notebooks"

all: build

data:
	$(PY) src/generate_sample.py

build:
	$(PY) src/build.py

html:
	$(PY) src/build_html.py

# `-m nbconvert`, not `-m jupyter nbconvert`: the jupyter dispatcher looks the
# subcommand up on PATH and can silently run ANOTHER env's nbconvert + kernel.
notebooks:
	$(PY) -m nbconvert --to notebook --execute --inplace \
		--ExecutePreprocessor.timeout=900 notebooks/*.ipynb

clean:
	rm -rf data/processed/* dashboard/extracts/*
	@echo "cleaned processed data and extracts"
