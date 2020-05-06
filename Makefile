TEST_PATH=./vbus/tests
DOC_PATH=./docs
SCENARIO_REPO=./vbus/tests/scenarios

clean-pyc:
	find . -name '*.pyc' -exec rm --force {} +
	find . -name '*.pyo' -exec rm --force {} +

test-init:
	pip install -r requirements-tests.txt
	( cd $(TEST_PATH) ; git clone git@bitbucket.org:vbus/scenarios.git )

test: clean-pyc
	python -m unittest discover $(TEST_PATH)


install-doc-requirements:
	pip install -r docs/requirements.txt

doc: install-doc-requirements
	( cd $(DOC_PATH) ; make html )